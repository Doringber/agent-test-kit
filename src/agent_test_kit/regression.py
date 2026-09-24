"""Portable regression case schemas, loaders, and deterministic evaluation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import AliasChoices, BaseModel, Field, ValidationError, model_validator

from agent_test_kit.assertions.flow import (
    FlowAssertionEngine,
    validate_call_count_constraints,
)
from agent_test_kit.models.enums import ToolCallStatus
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.repetition import (
    AsyncAgentExecutor,
    AsyncExecutionCallable,
    run_repeatedly,
)
from agent_test_kit.scoring import (
    ForbiddenTermsScorer,
    RequiredFieldsScorer,
    RequiredTermsScorer,
    Scorer,
    evaluate_score,
)

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
BuiltinScorer = RequiredTermsScorer | ForbiddenTermsScorer | RequiredFieldsScorer


class RegressionCaseLoadError(ValueError):
    """A regression case file cannot be parsed or validated."""


class RegressionToolExpectation(BaseModel):
    """Expected invocation details for one tool."""

    server: str | None = None
    name: str = Field(min_length=1)
    status: ToolCallStatus | None = None
    arguments: dict[str, Any] | None = None
    exact_calls: int | None = Field(default=None, ge=0)
    min_calls: int | None = Field(default=None, ge=0)
    max_calls: int | None = Field(default=None, ge=0)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_count_constraints(self) -> Self:
        try:
            validate_call_count_constraints(
                self.exact_calls,
                self.min_calls,
                self.max_calls,
            )
        except ValueError as exc:
            raise ValueError(f"invalid count constraints: {exc}") from exc
        return self


class RegressionExpectedOutcome(BaseModel):
    """Declarative deterministic expectations for a regression case."""

    success: bool
    required_tools: list[RegressionToolExpectation] = Field(default_factory=list)
    forbidden_tools: list[RegressionToolExpectation] = Field(default_factory=list)
    order: list[RegressionToolExpectation] = Field(
        default_factory=list,
        validation_alias=AliasChoices("order", "tool_order"),
    )
    counts: list[RegressionToolExpectation] = Field(
        default_factory=list,
        validation_alias=AliasChoices("counts", "tool_counts"),
    )
    argument_expectations: list[RegressionToolExpectation] = Field(default_factory=list)
    no_failed_calls: bool = False
    read_only: bool = False

    model_config = {"extra": "forbid"}


class RegressionBehavior(BaseModel):
    """Behavior expectations for outputs that have no single expected result.

    Built-in checks run in ``evaluate``. Named ``scores`` refer to consumer-provided
    scorers and are applied by ``evaluate_runs`` and ``run``.
    """

    min_pass_rate: float = Field(default=1.0, gt=0.0, le=1.0)
    required_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    scores: dict[str, UnitInterval] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    def builtin_scorers(self) -> list[BuiltinScorer]:
        scorers: list[BuiltinScorer] = []
        if self.required_terms:
            scorers.append(
                RequiredTermsScorer(self.required_terms, case_sensitive=self.case_sensitive)
            )
        if self.forbidden_terms:
            scorers.append(
                ForbiddenTermsScorer(self.forbidden_terms, case_sensitive=self.case_sensitive)
            )
        if self.required_fields:
            scorers.append(RequiredFieldsScorer(self.required_fields))
        return scorers


class RegressionEvaluation(BaseModel):
    """Evaluation of one run, suitable for ordinary pytest assertions."""

    case_id: str
    passed: bool
    failures: tuple[str, ...] = ()
    scores: dict[str, float] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def assert_passed(self) -> None:
        if not self.passed:
            raise AssertionError(
                f"Regression case {self.case_id!r} failed: {'; '.join(self.failures)}"
            )


class RegressionRunEvaluation(BaseModel):
    """Evaluation of a case across repeated runs against its minimum pass rate."""

    case_id: str
    goal: str | None = None
    persona: str | None = None
    passed: bool
    pass_rate: float
    min_pass_rate: float
    runs: tuple[RegressionEvaluation, ...]

    model_config = {"frozen": True}

    def assert_passed(self) -> None:
        if self.passed:
            return
        passed_runs = sum(run.passed for run in self.runs)
        failed = [
            f"run {index}: {'; '.join(run.failures)}"
            for index, run in enumerate(self.runs, start=1)
            if not run.passed
        ]
        raise AssertionError(
            f"Regression case {self.case_id!r} pass rate {self.pass_rate:.0%} "
            f"({passed_runs}/{len(self.runs)}) is below {self.min_pass_rate:.0%}. "
            f"Failures: {' | '.join(failed)}"
        )


class RegressionCase(BaseModel):
    """A portable production regression represented as data."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input: dict[str, Any]
    expected_outcome: RegressionExpectedOutcome
    goal: str | None = Field(default=None, min_length=1)
    persona: str | None = Field(default=None, min_length=1)
    runs: int = Field(default=1, ge=1, le=100)
    behavior: RegressionBehavior | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"extra": "forbid"}

    def evaluate(self, result: AgentExecutionResult) -> RegressionEvaluation:
        """Evaluate deterministic expectations and built-in behavior checks for one run."""
        failures, scores = self._deterministic_failures(result)
        return RegressionEvaluation(
            case_id=self.id,
            passed=not failures,
            failures=tuple(failures),
            scores=scores,
        )

    async def evaluate_runs(
        self,
        results: Sequence[AgentExecutionResult],
        *,
        scorers: Iterable[Scorer] = (),
    ) -> RegressionRunEvaluation:
        """Evaluate every run, including named scores, against ``min_pass_rate``."""
        if not results:
            raise ValueError(f"Regression case {self.id!r} requires at least one result")
        named_scorers = self._resolve_scorers(scorers)
        thresholds = self.behavior.scores if self.behavior else {}

        evaluations: list[RegressionEvaluation] = []
        for result in results:
            failures, scores = self._deterministic_failures(result)
            for name, minimum in thresholds.items():
                score = await evaluate_score(named_scorers[name], result)
                scores[name] = score.value
                if score.value < minimum:
                    detail = f" ({score.reason})" if score.reason else ""
                    failures.append(
                        f"Score {name!r}: expected >= {minimum:.2f}. "
                        f"Observed: {score.value:.2f}{detail}"
                    )
            evaluations.append(
                RegressionEvaluation(
                    case_id=self.id,
                    passed=not failures,
                    failures=tuple(failures),
                    scores=scores,
                )
            )

        min_pass_rate = self.behavior.min_pass_rate if self.behavior else 1.0
        pass_rate = sum(evaluation.passed for evaluation in evaluations) / len(evaluations)
        return RegressionRunEvaluation(
            case_id=self.id,
            goal=self.goal,
            persona=self.persona,
            passed=pass_rate >= min_pass_rate,
            pass_rate=pass_rate,
            min_pass_rate=min_pass_rate,
            runs=tuple(evaluations),
        )

    async def run(
        self,
        executor: AsyncAgentExecutor | AsyncExecutionCallable,
        *,
        scorers: Iterable[Scorer] = (),
        idempotency_key: str | None = None,
    ) -> RegressionRunEvaluation:
        """Execute the case ``runs`` times with one idempotency key and evaluate all runs."""
        scorer_list = list(scorers)
        self._resolve_scorers(scorer_list)
        aggregate = await run_repeatedly(
            executor,
            input=self.input,
            runs=self.runs,
            idempotency_key=idempotency_key or f"regression:{self.id}",
        )
        return await self.evaluate_runs(aggregate.results, scorers=scorer_list)

    def _resolve_scorers(self, scorers: Iterable[Scorer]) -> dict[str, Scorer]:
        named: dict[str, Scorer] = {}
        for scorer in scorers:
            if scorer.name in named:
                raise ValueError(f"Duplicate scorer name {scorer.name!r}")
            named[scorer.name] = scorer
        required = self.behavior.scores if self.behavior else {}
        missing = sorted(set(required) - set(named))
        if missing:
            raise ValueError(
                f"Regression case {self.id!r} declares scores with no matching scorer: {missing}"
            )
        return named

    def _deterministic_failures(
        self, result: AgentExecutionResult
    ) -> tuple[list[str], dict[str, float]]:
        expected = self.expected_outcome
        engine = FlowAssertionEngine(result)
        failures: list[str] = []

        if result.success != expected.success:
            failures.append(f"Expected success={expected.success}. Observed: {result.success}")

        for tool in expected.required_tools:
            _capture_assertion(
                failures,
                f"Required tool {_tool_label(tool)!r}",
                partial(
                    engine.assert_tool_called,
                    tool.name,
                    server=tool.server,
                    status=tool.status or ToolCallStatus.SUCCESS,
                    arguments=tool.arguments,
                ),
            )
            _evaluate_declared_count(
                engine,
                tool,
                failures,
                status=tool.status or ToolCallStatus.SUCCESS,
            )

        for tool in expected.argument_expectations:
            _capture_assertion(
                failures,
                f"Tool arguments for {_tool_label(tool)!r}",
                partial(
                    engine.assert_tool_called,
                    tool.name,
                    server=tool.server,
                    status=tool.status,
                    arguments=tool.arguments,
                ),
            )

        for tool in expected.forbidden_tools:
            matching = engine.matching_calls(
                tool.name,
                server=tool.server,
                status=tool.status,
                arguments=tool.arguments,
            )
            if matching:
                failures.append(
                    f"Forbidden tool {_tool_label(tool)!r} was called {len(matching)} time(s)."
                )

        for before, after in zip(expected.order, expected.order[1:], strict=False):
            _capture_assertion(
                failures,
                f"Tool order {_tool_label(before)!r} before {_tool_label(after)!r}",
                partial(
                    engine.assert_tool_order,
                    before=(before.server, before.name),
                    after=(after.server, after.name),
                    before_status=before.status or ToolCallStatus.SUCCESS,
                    after_status=after.status or ToolCallStatus.SUCCESS,
                ),
            )

        for tool in expected.counts:
            if tool.exact_calls is None and tool.min_calls is None and tool.max_calls is None:
                failures.append(f"Count expectation for {_tool_label(tool)!r} declares no bounds.")
            else:
                _evaluate_declared_count(
                    engine,
                    tool,
                    failures,
                    status=tool.status,
                )

        if expected.no_failed_calls:
            _capture_assertion(
                failures,
                "No failed tool calls",
                engine.assert_no_failed_tool_calls,
            )
        if expected.read_only:
            _capture_assertion(failures, "Read-only workflow", engine.assert_read_only)

        scores: dict[str, float] = {}
        for scorer in self.behavior.builtin_scorers() if self.behavior else []:
            score = scorer.score(result)
            scores[scorer.name] = score.value
            if score.value < 1.0:
                failures.append(f"Behavior {scorer.name!r}: {score.reason}")

        return failures, scores


def load_regression_cases(path: str | Path) -> list[RegressionCase]:
    """Load and validate regression cases from a YAML or JSON file."""
    case_path = Path(path)
    try:
        text = case_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegressionCaseLoadError(
            f"{case_path}: unable to read regression cases: {exc}"
        ) from exc

    try:
        match case_path.suffix.lower():
            case ".json":
                payload = json.loads(text)
            case ".yaml" | ".yml":
                payload = yaml.safe_load(text)
            case extension:
                raise RegressionCaseLoadError(
                    f"{case_path}: unsupported regression case extension {extension!r}"
                )
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise RegressionCaseLoadError(
            f"{case_path}: unable to parse regression cases: {exc}"
        ) from exc

    raw_cases = _extract_raw_cases(payload, case_path)
    cases: list[RegressionCase] = []
    for index, raw_case in enumerate(raw_cases):
        case_id = raw_case.get("id", "<unknown>") if isinstance(raw_case, dict) else "<unknown>"
        try:
            cases.append(RegressionCase.model_validate(raw_case))
        except ValidationError as exc:
            raise RegressionCaseLoadError(
                f"{case_path}: case[{index}] id={case_id!r} failed schema validation: "
                f"{exc.errors(include_url=False)!r}"
            ) from exc
    return cases


def _extract_raw_cases(payload: Any, path: Path) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if isinstance(cases, list):
            return cases
    raise RegressionCaseLoadError(
        f"{path}: expected a list of cases or an object containing a 'cases' list"
    )


def _evaluate_declared_count(
    engine: FlowAssertionEngine,
    tool: RegressionToolExpectation,
    failures: list[str],
    *,
    status: ToolCallStatus | None,
) -> None:
    if tool.exact_calls is None and tool.min_calls is None and tool.max_calls is None:
        return
    _capture_assertion(
        failures,
        f"Tool count for {_tool_label(tool)!r}",
        lambda: engine.assert_tool_call_count(
            tool.name,
            server=tool.server,
            exact=tool.exact_calls,
            min_calls=tool.min_calls,
            max_calls=tool.max_calls,
            status=status,
            arguments=tool.arguments,
        ),
    )


def _capture_assertion(
    failures: list[str],
    label: str,
    assertion: Callable[[], None],
) -> None:
    try:
        assertion()
    except AssertionError as exc:
        failures.append(f"{label}: {exc}")


def _tool_label(tool: RegressionToolExpectation) -> str:
    return f"{tool.server}/{tool.name}" if tool.server else tool.name
