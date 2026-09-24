"""Behavior scoring contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_test_kit import (
    AgentExecutionResult,
    AgentTestConfig,
    ForbiddenTermsScorer,
    JsonReportWriter,
    RepeatedExecutionResult,
    RequiredFieldsScorer,
    RequiredTermsScorer,
    RunContext,
    Score,
    Scorer,
    response_text,
    run_repeatedly,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

pytestmark = pytest.mark.agent_unit


def _result(response: Any, *, success: bool = True) -> AgentExecutionResult:
    return AgentExecutionResult(success=success, run_id="run-1", response=response)


class FixedScorer:
    """Async scorer that returns a preset value, standing in for an LLM judge."""

    def __init__(self, value: float, *, name: str = "judge") -> None:
        self.value = value
        self.name = name

    async def score(self, result: AgentExecutionResult) -> Score:
        return Score(self.value, reason="judge rationale")


class SequenceScorer:
    """Sync scorer returning successive values across repeated runs."""

    name = "sequence"

    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def score(self, result: AgentExecutionResult) -> Score:
        return Score(next(self._values))


class BadScorer:
    name = "bad"

    def score(self, result: AgentExecutionResult) -> Any:
        return 0.9


class ScriptedExecutor:
    """Returns one scripted response per run."""

    def __init__(self, responses: list[Any], *, write_on_run: int | None = None) -> None:
        self._responses = iter(responses)
        self._run = 0
        self._write_on_run = write_on_run

    async def execute(
        self,
        input: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        self._run += 1
        calls = []
        if self._run == self._write_on_run:
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
            run_id=f"run-{self._run}",
            response=next(self._responses),
            trace=AgentTrace(tool_calls=calls),
        )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, ""),
        ("plain text", "plain text"),
        ({"b": 1, "a": "שלום"}, '{"a": "שלום", "b": 1}'),
        (["x", 2], '["x", 2]'),
    ],
)
def test_response_text_renders_supported_shapes(response: Any, expected: str) -> None:
    assert response_text(_result(response)) == expected


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan")])
def test_score_rejects_values_outside_unit_interval(value: float) -> None:
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        Score(value)


@pytest.mark.parametrize("value", [True, "0.5", None])
def test_score_rejects_non_numeric_values(value: Any) -> None:
    with pytest.raises(TypeError, match="must be a number"):
        Score(value)


@pytest.mark.parametrize(
    ("response", "expected_value", "missing"),
    [
        ("Refund for ORDER 123 is Pending", 1.0, []),
        ("Order 123 received", 0.5, ["pending"]),
        ({"note": "nothing useful"}, 0.0, ["order 123", "pending"]),
    ],
)
def test_required_terms_scores_fraction_found(
    response: Any, expected_value: float, missing: list[str]
) -> None:
    score = RequiredTermsScorer(["order 123", "pending"]).score(_result(response))

    assert score.value == expected_value
    assert score.details == {"missing": missing}
    assert (score.reason is None) == (not missing)


def test_required_terms_can_be_case_sensitive() -> None:
    scorer = RequiredTermsScorer(["Pending"], case_sensitive=True)

    assert scorer.score(_result("status: pending")).value == 0.0
    assert scorer.score(_result("status: Pending")).value == 1.0


@pytest.mark.parametrize(
    ("response", "expected_value", "found"),
    [
        ("Your refund is being reviewed", 1.0, []),
        ("Here is the API KEY: abc", 0.0, ["api key"]),
        ({"debug": "system prompt and api key"}, 0.0, ["system prompt", "api key"]),
    ],
)
def test_forbidden_terms_is_binary(response: Any, expected_value: float, found: list[str]) -> None:
    score = ForbiddenTermsScorer(["system prompt", "api key"]).score(_result(response))

    assert score.value == expected_value
    assert score.details == {"found": found}


@pytest.mark.parametrize(
    ("response", "expected_value", "missing"),
    [
        ({"order": {"id": 123, "status": "pending"}}, 1.0, []),
        ({"order": {"id": 123, "status": None}}, 0.5, ["order.status"]),
        ({"order": "123"}, 0.0, ["order.id", "order.status"]),
    ],
)
def test_required_fields_supports_dotted_paths(
    response: Any, expected_value: float, missing: list[str]
) -> None:
    score = RequiredFieldsScorer(["order.id", "order.status"]).score(_result(response))

    assert score.value == expected_value
    assert score.details == {"missing": missing}


def test_required_fields_rejects_non_mapping_response() -> None:
    score = RequiredFieldsScorer(["status"]).score(_result("status: ok"))

    assert score.value == 0.0
    assert score.reason == "Response is not a JSON object"


@pytest.mark.parametrize(
    "factory",
    [RequiredTermsScorer, ForbiddenTermsScorer, RequiredFieldsScorer],
)
@pytest.mark.parametrize("terms", [[], [""]])
def test_builtin_scorers_reject_empty_terms(factory: Any, terms: list[str]) -> None:
    with pytest.raises(ValueError):
        factory(terms)


def test_builtin_and_custom_scorers_satisfy_protocol() -> None:
    assert isinstance(RequiredTermsScorer(["x"]), Scorer)
    assert isinstance(FixedScorer(0.5), Scorer)


@pytest.mark.asyncio
async def test_assert_score_records_passing_outcome() -> None:
    result = _result("Order 123 is pending")

    score = await result.assert_score(RequiredTermsScorer(["order 123"]), min_score=1.0)

    assert score.value == 1.0
    outcome = result.assertion_outcomes[-1]
    assert outcome.name == "assert_score"
    assert outcome.passed is True
    assert outcome.expected == {"scorer": "required_terms", "min_score": 1.0}
    assert outcome.actual == {"score": 1.0, "reason": None, "details": {"missing": []}}


@pytest.mark.asyncio
async def test_assert_score_fails_below_threshold_with_reason() -> None:
    result = _result("anything")

    with pytest.raises(AssertionError, match=r"judge score >= 0\.80\. Observed: 0\.60"):
        await result.assert_score(FixedScorer(0.6), min_score=0.8)

    outcome = result.assertion_outcomes[-1]
    assert outcome.passed is False
    assert outcome.actual["score"] == 0.6
    assert "judge rationale" in (outcome.message or "")


@pytest.mark.asyncio
async def test_assert_score_passes_at_exact_threshold() -> None:
    await _result("x").assert_score(FixedScorer(0.8), min_score=0.8)


@pytest.mark.asyncio
@pytest.mark.parametrize("min_score", [-0.1, 1.5])
async def test_assert_score_rejects_invalid_threshold(min_score: float) -> None:
    result = _result("x")

    with pytest.raises(ValueError, match="min_score"):
        await result.assert_score(FixedScorer(0.9), min_score=min_score)
    assert result.assertion_outcomes == []


@pytest.mark.asyncio
async def test_assert_score_rejects_scorer_with_wrong_return_type() -> None:
    with pytest.raises(TypeError, match="must return Score"):
        await _result("x").assert_score(BadScorer(), min_score=0.5)


@pytest.mark.asyncio
async def test_score_outcome_reaches_json_report(tmp_path: Path) -> None:
    result = _result("Order 123")
    with pytest.raises(AssertionError):
        await result.assert_score(RequiredTermsScorer(["order 123", "pending"]), min_score=0.9)

    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="billing-agent", environment="unit"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="refund_status",
        nodeid="tests/test_x.py::refund_status",
        passed=False,
        duration_ms=1,
        markers=["agent_unit"],
        execution_result=result,
    )
    report = writer.build_report()

    assertion = report.scenarios[0].assertions[0]
    assert assertion.name == "assert_score"
    assert assertion.passed is False
    assert assertion.actual["score"] == 0.5


@pytest.mark.asyncio
async def test_assert_pass_rate_tolerates_variance_within_threshold() -> None:
    responses = ["Order 123 pending", "Order 123 is pending", "cannot find order", "pending: 123"]
    aggregate = await run_repeatedly(
        ScriptedExecutor(responses), input={"order": 123}, runs=4, idempotency_key="k"
    )

    rate = aggregate.assert_pass_rate(
        lambda r: "pending" in response_text(r).casefold(), min_rate=0.75
    )

    assert rate == 0.75


@pytest.mark.asyncio
async def test_assert_pass_rate_reports_failing_runs() -> None:
    aggregate = await run_repeatedly(
        ScriptedExecutor(["ok", "bad", "ok", "bad"]), input={}, runs=4, idempotency_key="k"
    )

    with pytest.raises(AssertionError, match=r"Observed: 50% \(2/4\); failing runs: \[2, 4\]"):
        aggregate.assert_pass_rate(lambda r: r.response == "ok", min_rate=0.8)


@pytest.mark.asyncio
async def test_assert_pass_rate_counts_assertion_errors_as_failed_runs() -> None:
    aggregate = await run_repeatedly(
        ScriptedExecutor(["a", "b", "c"], write_on_run=2), input={}, runs=3, idempotency_key="k"
    )

    def read_only(result: AgentExecutionResult) -> bool:
        result.assert_read_only()
        return True

    assert aggregate.assert_pass_rate(read_only, min_rate=0.6) == pytest.approx(2 / 3)
    with pytest.raises(AssertionError, match=r"failing runs: \[2\]"):
        aggregate.assert_pass_rate(read_only, min_rate=1.0)


@pytest.mark.asyncio
async def test_assert_pass_rate_propagates_unexpected_errors() -> None:
    aggregate = await run_repeatedly(
        ScriptedExecutor([None]), input={}, runs=1, idempotency_key="k"
    )

    def broken(result: AgentExecutionResult) -> bool:
        raise KeyError("missing")

    with pytest.raises(KeyError):
        aggregate.assert_pass_rate(broken, min_rate=0.5)


@pytest.mark.asyncio
async def test_assert_score_rate_uses_score_threshold_per_run() -> None:
    aggregate = await run_repeatedly(
        ScriptedExecutor(["a", "b", "c", "d", "e"]), input={}, runs=5, idempotency_key="k"
    )

    rate = await aggregate.assert_score_rate(
        SequenceScorer([0.9, 0.85, 0.4, 0.8, 0.95]), min_score=0.8, min_rate=0.8
    )

    assert rate == 0.8


@pytest.mark.asyncio
async def test_assert_score_rate_fails_below_rate() -> None:
    aggregate = await run_repeatedly(
        ScriptedExecutor(["a", "b"]), input={}, runs=2, idempotency_key="k"
    )

    with pytest.raises(AssertionError, match=r"sequence >= 0\.80 pass rate >= 100%"):
        await aggregate.assert_score_rate(SequenceScorer([0.9, 0.1]), min_score=0.8, min_rate=1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"min_score": 1.2, "min_rate": 0.5}, "min_score"),
        ({"min_score": 0.5, "min_rate": -1.0}, "min_rate"),
    ],
)
async def test_assert_score_rate_validates_thresholds(kwargs: dict[str, float], label: str) -> None:
    aggregate = await run_repeatedly(ScriptedExecutor(["a"]), input={}, runs=1, idempotency_key="k")

    with pytest.raises(ValueError, match=label):
        await aggregate.assert_score_rate(FixedScorer(0.9), **kwargs)


def test_pass_rate_requires_results() -> None:
    empty = RepeatedExecutionResult(results=(), contexts=(), idempotency_key="k")

    with pytest.raises(ValueError, match="at least one run"):
        empty.assert_pass_rate(lambda r: True, min_rate=0.5)
    with pytest.raises(ValueError, match="min_rate"):
        empty.assert_pass_rate(lambda r: True, min_rate=2.0)
