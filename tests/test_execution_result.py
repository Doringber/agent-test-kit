"""AgentExecutionResult parsing tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.run_context import RunContext


@pytest.mark.agent_unit
def test_from_api_response_uses_run_context() -> None:
    context = RunContext()
    payload = {
        "success": True,
        "trace": {
            "tool_calls": [{"server": "jira", "name": "create_issue"}],
        },
    }
    result = AgentExecutionResult.from_api_response(payload, run_context=context)
    assert result.run_id == context.run_id
    assert result.trace_id == context.trace_id
    assert result.correlation_id == context.correlation_id
    assert len(result.tool_calls) == 1


@pytest.mark.agent_unit
def test_assert_success_raises_on_failure() -> None:
    result = AgentExecutionResult(success=False, run_id="run_1", error="boom")
    with pytest.raises(AssertionError, match="boom"):
        result.assert_success()
