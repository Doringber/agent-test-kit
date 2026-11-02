"""Evals: registration, scoring, and known-good / known-bad traces."""

from __future__ import annotations

from typing import Any

import pytest

from agent_test_kit import (
    AgentExecutionResult,
    Eval,
    RequiredTermsEval,
    RequiredToolsEval,
    Score,
    ToolCall,
    eval_case,
    get_eval,
    register_eval,
    response_text,
    run_evals,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.trace import AgentTrace

pytestmark = pytest.mark.agent_unit


def _result(
    response: str = "",
    calls: list[ToolCall] | None = None,
) -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="run-eval",
        response=response,
        trace=AgentTrace(tool_calls=list(calls or [])),
    )


def _call(name: str, *, server: str | None = None) -> ToolCall:
    return ToolCall(
        server=server,
        name=name,
        status=ToolCallStatus.SUCCESS,
        operation_kind=ToolOperationKind.READ,
    )


@pytest.mark.parametrize(
    ("response", "expect_pass"),
    [
        ("Your refund for order 123 is pending.", True),
        ("I don't know.", False),
        ("The refund is pending.", False),
    ],
)
def test_required_terms_eval_known_traces(response: str, expect_pass: bool) -> None:
    evaluation = RequiredTermsEval(["refund", "123"])
    result = evaluation.evaluate(_result(response))
    assert result.passed is expect_pass
    assert result.name == "required_terms"
    if expect_pass:
        assert result.score == 1.0
        result.assert_passed()
    else:
        assert result.score < 1.0
        with pytest.raises(AssertionError, match="required_terms"):
            result.assert_passed()


@pytest.mark.parametrize(
    ("calls", "expect_pass"),
    [
        (
            [_call("get_invoice", server="billing"), _call("create_issue", server="jira")],
            True,
        ),
        ([_call("get_invoice", server="billing")], False),
        ([], False),
    ],
)
def test_required_tools_eval_known_traces(calls: list[ToolCall], expect_pass: bool) -> None:
    evaluation = RequiredToolsEval([("billing", "get_invoice"), ("jira", "create_issue")])
    result = evaluation.evaluate(_result("done", calls))
    assert result.passed is expect_pass
    if expect_pass:
        assert result.score == 1.0
        result.assert_passed()
    else:
        assert result.score < 1.0
        assert "missing" in result.details
        with pytest.raises(AssertionError, match="required_tools"):
            result.assert_passed()


def test_required_terms_threshold_boundary() -> None:
    evaluation = RequiredTermsEval(["refund", "123"], threshold=0.5, name="refund_partial")
    partial = evaluation.evaluate(_result("The refund is pending."))
    assert partial.score == 0.5
    partial.assert_passed()
    missed = evaluation.evaluate(_result("nothing"))
    assert missed.score == 0.0
    with pytest.raises(AssertionError):
        missed.assert_passed()


def test_assert_evals_records_failure_and_success() -> None:
    bad = _result("nope")
    with pytest.raises(AssertionError, match="required_terms"):
        bad.assert_evals(RequiredTermsEval(["refund"]))
    assert bad.assertion_outcomes[-1].name == "assert_evals"
    assert bad.assertion_outcomes[-1].passed is False
    assert bad.eval_checks[0].passed is False

    mixed = _result("refund ready")
    with pytest.raises(AssertionError, match="required_tools"):
        mixed.assert_evals([RequiredTermsEval(["refund"]), RequiredToolsEval(["lookup"])])
    assert mixed.eval_checks[0].passed is True
    assert mixed.eval_checks[1].passed is False

    passed = _result("refund ready", [_call("lookup")])
    report = passed.assert_evals([RequiredTermsEval(["refund"]), RequiredToolsEval(["lookup"])])
    assert report.passed
    assert passed.assertion_outcomes[-1].passed is True


def test_eval_case_registers_and_runs() -> None:
    @eval_case(name="kit_mentions_ready", threshold=1.0)
    def mentions_ready(result: AgentExecutionResult) -> float:
        return 1.0 if "ready" in response_text(result).casefold() else 0.0

    assert get_eval("kit_mentions_ready") is mentions_ready
    run_evals(_result("system ready"), mentions_ready).assert_passed()
    bad = run_evals(_result("not yet"), mentions_ready)
    assert not bad.passed
    with pytest.raises(AssertionError, match="kit_mentions_ready"):
        bad.assert_passed()


def test_eval_case_bool_and_score_returns() -> None:
    from agent_test_kit import registered_evals

    @eval_case(name="kit_bool_eval", register=True)
    def as_bool(result: AgentExecutionResult) -> bool:
        return bool(response_text(result))

    @eval_case(name="kit_score_eval", threshold=0.8, register=False)
    def as_score(result: AgentExecutionResult) -> Score:
        return Score(0.8, reason="judge", details={"source": "test"})

    assert as_bool.evaluate(_result("")).score == 0.0
    assert as_bool.evaluate(_result("hi")).passed is True
    scored = as_score.evaluate(_result("hi"))
    assert scored.passed is True
    assert scored.reason == "judge"
    assert scored.details == {"source": "test"}
    with pytest.raises(ValueError, match="already registered"):
        eval_case(name="kit_bool_eval")(lambda result: 1.0)
    register_eval(as_bool)
    assert "kit_bool_eval" in registered_evals()
    assert "kit_score_eval" not in registered_evals()


def test_eval_rejects_bad_scores_and_empty_input() -> None:
    class BadEval(Eval):
        name = "kit_bad_eval"

        def score(self, result: AgentExecutionResult) -> Any:
            return "high"

    class AsyncEval(Eval):
        name = "kit_async_eval"

        def score(self, result: AgentExecutionResult) -> Any:
            async def inner() -> float:
                return 1.0

            return inner()

    with pytest.raises(TypeError, match="kit_bad_eval"):
        BadEval().evaluate(_result("x"))
    with pytest.raises(TypeError, match="awaitable"):
        AsyncEval().evaluate(_result("x"))
    with pytest.raises(ValueError, match="between"):
        RequiredTermsEval(["ok"], threshold=1.5)
    with pytest.raises(ValueError, match="at least one"):
        run_evals(_result("x"), [])
    with pytest.raises(ValueError, match="at least one"):
        RequiredToolsEval([])
    with pytest.raises(ValueError, match="names or"):
        RequiredToolsEval([("only-server",)])  # type: ignore[list-item]
    with pytest.raises(KeyError, match="not_a_real_eval"):
        get_eval("not_a_real_eval")
    with pytest.raises(TypeError, match="Expected Eval"):
        run_evals(_result("x"), ["nope"])  # type: ignore[arg-type]


@eval_case(name="kit_marker_mentions_ready")
def kit_marker_mentions_ready(result: AgentExecutionResult) -> float:
    return 1.0 if "ready" in response_text(result).casefold() else 0.0


@pytest.mark.agent_eval("kit_marker_mentions_ready")
def test_agent_eval_marker_passes_a_known_good_trace(agent_eval: Any) -> None:
    report = agent_eval.run(_result("system ready"))
    report.assert_passed()
    assert report.results[0].score == 1.0


@pytest.mark.agent_eval("kit_marker_mentions_ready")
def test_agent_eval_marker_fails_a_known_bad_trace(agent_eval: Any) -> None:
    with pytest.raises(AssertionError, match="kit_marker_mentions_ready"):
        agent_eval.run(_result("nope"))


def test_agent_eval_requires_a_selection(agent_eval: Any) -> None:
    with pytest.raises(RuntimeError, match="No evals"):
        agent_eval.run(_result("ready"))


def test_agent_eval_explicit_list_can_fail_closed(agent_eval: Any) -> None:
    report = agent_eval.run(
        _result("refund"),
        RequiredTermsEval(["refund"]),
        fail=False,
    )
    assert report.passed
    bad = agent_eval.run(_result("nope"), RequiredTermsEval(["refund"]), fail=False)
    assert not bad.passed
