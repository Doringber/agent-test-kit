"""Goal-based regression cases evaluated across repeated runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_test_kit import (
    AgentExecutionResult,
    RegressionCase,
    RegressionCaseLoadError,
    RunContext,
    Score,
    load_regression_cases,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

pytestmark = pytest.mark.agent_unit

EXAMPLE_CASES = Path(__file__).parents[1] / "examples" / "behavior_regression_cases.yaml"


def _case(**overrides: Any) -> RegressionCase:
    payload: dict[str, Any] = {
        "id": "refund-status",
        "source": "PROD-1",
        "description": "Refund status lookup",
        "goal": "User learns refund status",
        "persona": "frustrated_customer",
        "runs": 4,
        "input": {"order_id": 123},
        "expected_outcome": {"success": True, "read_only": True},
        "behavior": {
            "min_pass_rate": 0.75,
            "required_terms": ["123"],
            "forbidden_terms": ["api key"],
        },
        "created_at": "2026-09-24T00:00:00Z",
    }
    payload.update(overrides)
    return RegressionCase.model_validate(payload)


def _result(response: Any, *, write: bool = False, run: int = 1) -> AgentExecutionResult:
    calls = []
    if write:
        calls.append(
            ToolCall(
                server="billing",
                name="issue_refund",
                operation_kind=ToolOperationKind.WRITE,
                status=ToolCallStatus.SUCCESS,
            )
        )
    return AgentExecutionResult(
        success=True,
        run_id=f"run-{run}",
        response=response,
        trace=AgentTrace(tool_calls=calls),
    )


class ScriptedExecutor:
    def __init__(self, results: list[AgentExecutionResult]) -> None:
        self._results = iter(results)
        self.inputs: list[dict[str, Any]] = []
        self.keys: list[str | None] = []

    async def execute(
        self,
        input: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        self.inputs.append(input)
        self.keys.append(run_context.idempotency_key if run_context else None)
        return next(self._results)


class NamedScorer:
    def __init__(self, name: str, values: list[float]) -> None:
        self.name = name
        self._values = iter(values)

    async def score(self, result: AgentExecutionResult) -> Score:
        return Score(next(self._values), reason=f"{self.name} rationale")


def test_example_yaml_loads_goal_cases() -> None:
    cases = load_regression_cases(EXAMPLE_CASES)

    assert [case.id for case in cases] == [
        "refund_status_frustrated_customer",
        "order_lookup_structured",
    ]
    first = cases[0]
    assert first.goal == "User learns the current refund status for order 123"
    assert first.persona == "frustrated_customer"
    assert first.runs == 5
    assert first.behavior is not None
    assert first.behavior.min_pass_rate == 0.8
    assert first.behavior.scores == {"groundedness": 0.8}


def test_cases_without_new_fields_keep_previous_defaults() -> None:
    case = _case(goal=None, persona=None, behavior=None, runs=1)

    evaluation = case.evaluate(_result("anything"))

    assert case.runs == 1
    assert evaluation.passed
    assert evaluation.scores == {}


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"runs": 0}, "runs"),
        ({"runs": 101}, "runs"),
        ({"goal": ""}, "goal"),
        ({"behavior": {"min_pass_rate": 0}}, "min_pass_rate"),
        ({"behavior": {"min_pass_rate": 1.5}}, "min_pass_rate"),
        ({"behavior": {"scores": {"judge": 1.2}}}, "scores"),
        ({"behavior": {"unknown": True}}, "unknown"),
    ],
)
def test_behavior_schema_validation(override: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        _case(**override)


def test_loader_reports_behavior_errors_with_case_context(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
cases:
  - id: broken-behavior
    source: PROD-2
    description: invalid threshold
    input: {}
    expected_outcome: {success: true}
    behavior: {min_pass_rate: 2}
    created_at: 2026-09-24T00:00:00Z
""",
        encoding="utf-8",
    )

    with pytest.raises(RegressionCaseLoadError, match=r"bad.yaml.*broken-behavior.*min_pass_rate"):
        load_regression_cases(path)


@pytest.mark.parametrize(
    ("response", "expected_failure", "scores"),
    [
        (
            "Refund for 123 is pending",
            None,
            {"required_terms": 1.0, "forbidden_terms": 1.0},
        ),
        (
            "Your refund is pending",
            "Behavior 'required_terms': Missing terms: ['123']",
            {"required_terms": 0.0, "forbidden_terms": 1.0},
        ),
        (
            "Order 123, api key abc",
            "Behavior 'forbidden_terms': Forbidden terms present: ['api key']",
            {"required_terms": 1.0, "forbidden_terms": 0.0},
        ),
    ],
)
def test_evaluate_applies_builtin_behavior_checks(
    response: str, expected_failure: str | None, scores: dict[str, float]
) -> None:
    evaluation = _case().evaluate(_result(response))

    assert evaluation.scores == scores
    if expected_failure is None:
        assert evaluation.passed
    else:
        assert evaluation.failures == (expected_failure,)


def test_evaluate_applies_required_fields() -> None:
    case = _case(behavior={"required_fields": ["order.status", "order.delivery_date"]})

    evaluation = case.evaluate(_result({"order": {"status": "shipped"}}))

    assert not evaluation.passed
    assert evaluation.scores == {"required_fields": 0.5}
    assert "order.delivery_date" in evaluation.failures[0]


@pytest.mark.asyncio
async def test_run_passes_when_variance_stays_within_pass_rate() -> None:
    executor = ScriptedExecutor(
        [
            _result("123 pending", run=1),
            _result("pending, order 123", run=2),
            _result("cannot find it", run=3),
            _result("123 approved", run=4),
        ]
    )

    evaluation = await _case().run(executor)

    assert evaluation.passed
    assert evaluation.pass_rate == 0.75
    assert evaluation.min_pass_rate == 0.75
    assert evaluation.goal == "User learns refund status"
    assert evaluation.persona == "frustrated_customer"
    assert [run.passed for run in evaluation.runs] == [True, True, False, True]
    assert executor.inputs == [{"order_id": 123}] * 4
    assert set(executor.keys) == {"regression:refund-status"}
    evaluation.assert_passed()


@pytest.mark.asyncio
async def test_run_fails_below_pass_rate_with_per_run_failures() -> None:
    executor = ScriptedExecutor(
        [
            _result("123 pending", run=1),
            _result("pending", run=2),
            _result("123", write=True, run=3),
            _result("123 ok", run=4),
        ]
    )

    evaluation = await _case().run(executor, idempotency_key="custom-key")

    assert not evaluation.passed
    assert evaluation.pass_rate == 0.5
    assert set(executor.keys) == {"custom-key"}
    with pytest.raises(AssertionError) as exc_info:
        evaluation.assert_passed()
    message = str(exc_info.value)
    assert "pass rate 50% (2/4) is below 75%" in message
    assert "run 2: Behavior 'required_terms'" in message
    assert "run 3: Read-only workflow" in message


@pytest.mark.asyncio
async def test_evaluate_runs_applies_named_scores() -> None:
    case = _case(behavior={"min_pass_rate": 0.5, "scores": {"groundedness": 0.8}})
    results = [_result("a", run=1), _result("b", run=2)]

    evaluation = await case.evaluate_runs(
        results, scorers=[NamedScorer("groundedness", [0.9, 0.4]), NamedScorer("unused", [])]
    )

    assert evaluation.passed
    assert [run.scores for run in evaluation.runs] == [
        {"groundedness": 0.9},
        {"groundedness": 0.4},
    ]
    assert evaluation.runs[1].failures == (
        "Score 'groundedness': expected >= 0.80. Observed: 0.40 (groundedness rationale)",
    )


@pytest.mark.asyncio
async def test_run_rejects_missing_scorer_before_executing() -> None:
    case = _case(behavior={"scores": {"groundedness": 0.8}})
    executor = ScriptedExecutor([])

    with pytest.raises(ValueError, match=r"no matching scorer: \['groundedness'\]"):
        await case.run(executor)
    assert executor.inputs == []


@pytest.mark.asyncio
async def test_evaluate_runs_rejects_duplicate_scorer_names() -> None:
    with pytest.raises(ValueError, match="Duplicate scorer name 'judge'"):
        await _case().evaluate_runs(
            [_result("123")], scorers=[NamedScorer("judge", []), NamedScorer("judge", [])]
        )


@pytest.mark.asyncio
async def test_evaluate_runs_requires_results() -> None:
    with pytest.raises(ValueError, match="at least one result"):
        await _case().evaluate_runs([])


@pytest.mark.asyncio
async def test_case_without_behavior_requires_every_run_to_pass() -> None:
    case = _case(behavior=None)

    evaluation = await case.evaluate_runs([_result("ok"), _result("x", write=True)])

    assert evaluation.min_pass_rate == 1.0
    assert evaluation.pass_rate == 0.5
    assert not evaluation.passed
