"""Repeated execution and idempotency contract tests."""

from __future__ import annotations

from typing import Any

import pytest

from agent_test_kit import AgentExecutionResult, RunContext, run_repeatedly
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace


class RecordingExecutor:
    """Deterministic executor used to verify context propagation."""

    def __init__(self, *, duplicate_writes: bool = False) -> None:
        self.contexts: list[RunContext] = []
        self.duplicate_writes = duplicate_writes

    async def execute(
        self,
        input: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        assert run_context is not None
        self.contexts.append(run_context)
        calls = []
        if self.duplicate_writes or len(self.contexts) == 1:
            calls.append(
                ToolCall(
                    server="jira",
                    name="create_issue",
                    arguments={"summary": input["summary"]},
                    operation_kind=ToolOperationKind.WRITE,
                    status=ToolCallStatus.SUCCESS,
                )
            )
        return AgentExecutionResult(
            success=True,
            run_id=run_context.run_id,
            response={"issue": "AI-123"},
            trace=AgentTrace(tool_calls=calls, model="deterministic"),
        )


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_repeated_execution_reuses_key_with_fresh_contexts() -> None:
    executor = RecordingExecutor()

    aggregate = await run_repeatedly(
        executor,
        input={"summary": "Regression"},
        runs=3,
        idempotency_key="stable-key",
    )

    assert len(aggregate.results) == 3
    assert aggregate.idempotency_key == "stable-key"
    assert {context.idempotency_key for context in aggregate.contexts} == {"stable-key"}
    assert len({context.run_id for context in aggregate.contexts}) == 3
    aggregate.assert_stable_success()
    aggregate.assert_no_duplicate_writes()
    aggregate.assert_responses_stable()


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_duplicate_write_assertion_compares_tool_and_arguments() -> None:
    aggregate = await run_repeatedly(
        RecordingExecutor(duplicate_writes=True),
        input={"summary": "Regression"},
        runs=2,
        idempotency_key="stable-key",
    )

    with pytest.raises(
        AssertionError,
        match=r"Duplicate writes across runs.*jira/create_issue",
    ):
        aggregate.assert_no_duplicate_writes()


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_stability_assertions_support_deterministic_callbacks() -> None:
    call_number = 0

    async def executor(
        input: dict[str, Any],
        context: RunContext,
    ) -> AgentExecutionResult:
        nonlocal call_number
        call_number += 1
        return AgentExecutionResult(
            success=True,
            run_id=context.run_id,
            response={"value": input["value"], "request": call_number},
            trace=AgentTrace(token_usage=call_number),
        )

    aggregate = await run_repeatedly(
        executor,
        input={"value": 7},
        runs=2,
        idempotency_key="same",
    )

    aggregate.assert_responses_stable(
        comparator=lambda first, current: first["value"] == current["value"],
    )
    aggregate.assert_traces_stable(
        comparator=lambda first, current: first.model == current.model,
    )
    with pytest.raises(AssertionError, match=r"responses to remain stable.*run 2"):
        aggregate.assert_responses_stable()


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_repeated_execution_accepts_context_strategy() -> None:
    executor = RecordingExecutor()

    def context_factory(index: int, idempotency_key: str) -> RunContext:
        return RunContext(
            run_id=f"repeat-{index}",
            trace_id=f"trace-{index}",
            correlation_id="shared-correlation",
            idempotency_key=idempotency_key,
        )

    aggregate = await run_repeatedly(
        executor,
        input={"summary": "Regression"},
        runs=2,
        idempotency_key="stable-key",
        context_factory=context_factory,
    )

    assert [context.run_id for context in aggregate.contexts] == ["repeat-0", "repeat-1"]
    assert {context.correlation_id for context in aggregate.contexts} == {"shared-correlation"}
