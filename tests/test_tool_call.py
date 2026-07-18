"""ToolCall model tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall


@pytest.mark.agent_unit
def test_tool_call_matches_server_and_name() -> None:
    call = ToolCall(server="bitbucket", name="get_pull_request")
    assert call.matches("get_pull_request", server="bitbucket")
    assert not call.matches("get_diff", server="bitbucket")
    assert call.matches("get_pull_request")


@pytest.mark.agent_unit
def test_tool_call_read_write_flags() -> None:
    read_call = ToolCall(name="read", operation_kind=ToolOperationKind.READ)
    write_call = ToolCall(name="write", operation_kind=ToolOperationKind.WRITE)
    assert read_call.is_read
    assert not read_call.is_write
    assert write_call.is_write
