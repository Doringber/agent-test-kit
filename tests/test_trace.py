"""AgentTrace parsing tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.trace import AgentTrace


@pytest.mark.agent_unit
def test_trace_from_payload() -> None:
    payload = {
        "tool_calls": [
            {
                "server": "bitbucket",
                "name": "get_pull_request",
                "operation_kind": "read",
            }
        ],
        "token_usage": 1500,
        "model": "gpt-4.1",
    }
    trace = AgentTrace.from_payload(payload)
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0].server == "bitbucket"
    assert trace.tool_calls[0].operation_kind == ToolOperationKind.READ
    assert trace.token_usage == 1500


@pytest.mark.agent_unit
def test_trace_from_empty_payload() -> None:
    trace = AgentTrace.from_payload(None)
    assert trace.tool_calls == []
