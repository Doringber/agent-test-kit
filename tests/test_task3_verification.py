"""Task 3 verifier orchestration and assertion outcome tests."""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from agent_test_kit import AgentExecutionResult
from agent_test_kit.verifiers import (
    VerificationContext,
    VerificationResult,
    run_verifiers,
)


class _Verifier:
    delays: ClassVar[dict[str, float]] = {"first": 0.02, "second": 0.0}

    def __init__(self, name: str, *, failure: BaseException | None = None) -> None:
        self.name = name
        self.failure = failure

    async def verify(self, context: VerificationContext) -> VerificationResult:
        await asyncio.sleep(self.delays.get(self.name, 0.0))
        if self.failure is not None:
            raise self.failure
        return VerificationResult(
            passed=True,
            message=context.run_id,
            evidence={"url": f"https://evidence.example/{self.name}"},
        )


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_run_verifiers_is_concurrent_ordered_and_aggregates_failures() -> None:
    execution = AgentExecutionResult(success=True, run_id="run_1")
    context = VerificationContext(
        run_id=execution.run_id,
        correlation_id=None,
        execution_result=execution,
    )

    summary = await run_verifiers(
        [
            _Verifier("first"),
            _Verifier("broken", failure=RuntimeError("database unavailable")),
            _Verifier("second"),
        ],
        context,
        timeout_seconds=0.1,
    )

    assert [result.verifier_name for result in summary.results] == [
        "first",
        "broken",
        "second",
    ]
    assert not summary.passed
    assert summary.failures[0].error_type == "RuntimeError"
    assert summary.evidence_links == [
        "https://evidence.example/first",
        "https://evidence.example/second",
    ]


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_run_verifiers_converts_timeout_and_continues() -> None:
    execution = AgentExecutionResult(success=True, run_id="run_timeout")
    context = VerificationContext(
        run_id=execution.run_id,
        correlation_id=None,
        execution_result=execution,
    )

    summary = await run_verifiers(
        [_Verifier("first"), _Verifier("second")],
        context,
        timeout_seconds=0.005,
    )

    assert [result.timed_out for result in summary.results] == [True, False]
    assert summary.results[0].passed is False
    assert summary.results[1].passed is True


@pytest.mark.agent_unit
def test_execution_assertions_capture_success_and_failure_before_reraising() -> None:
    result = AgentExecutionResult(
        success=False,
        run_id="run_assert",
        error="boom",
        assertions=["consumer-owned assertion"],
    )

    with pytest.raises(AssertionError, match="boom"):
        result.assert_success()

    assert result.assertions == ["consumer-owned assertion"]
    assert len(result.assertion_outcomes) == 1
    outcome = result.assertion_outcomes[0]
    assert outcome.name == "assert_success"
    assert outcome.passed is False
    assert outcome.expected is True
    assert outcome.actual is False
    assert outcome.message == "boom"

    passing = AgentExecutionResult(success=True, run_id="run_pass")
    passing.assert_success()
    assert passing.assertions == []
    assert passing.assertion_outcomes[0].passed is True
