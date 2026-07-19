"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall

pytest_plugins = ["pytester"]


@pytest.fixture
def sample_tool_calls() -> list[ToolCall]:
    return [
        ToolCall(
            id="1",
            server="bitbucket",
            name="get_pull_request",
            operation_kind=ToolOperationKind.READ,
            status=ToolCallStatus.SUCCESS,
        ),
        ToolCall(
            id="2",
            server="bitbucket",
            name="get_diff",
            operation_kind=ToolOperationKind.READ,
            status=ToolCallStatus.SUCCESS,
        ),
        ToolCall(
            id="3",
            server="jira",
            name="create_issue",
            operation_kind=ToolOperationKind.WRITE,
            status=ToolCallStatus.SUCCESS,
        ),
        ToolCall(
            id="4",
            server="bitbucket",
            name="add_comment",
            operation_kind=ToolOperationKind.WRITE,
            status=ToolCallStatus.SUCCESS,
        ),
    ]
