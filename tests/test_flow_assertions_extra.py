"""Additional flow assertion coverage."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace


def _result(calls: list[ToolCall]) -> AgentExecutionResult:
    return AgentExecutionResult(success=True, run_id="run", trace=AgentTrace(tool_calls=calls))


@pytest.mark.agent_unit
def test_assert_tool_sequence_allows_extra_reads() -> None:
    calls = [
        ToolCall(
            server="bitbucket", name="get_pull_request", operation_kind=ToolOperationKind.READ
        ),
        ToolCall(server="bitbucket", name="list_files", operation_kind=ToolOperationKind.READ),
        ToolCall(server="bitbucket", name="get_diff", operation_kind=ToolOperationKind.READ),
        ToolCall(server="jira", name="create_issue", operation_kind=ToolOperationKind.WRITE),
    ]
    result = _result(calls)
    result.assert_tool_sequence(
        [
            ("bitbucket", "get_pull_request"),
            ("bitbucket", "get_diff"),
            ("jira", "create_issue"),
        ],
        allow_additional_read_tools=True,
    )


@pytest.mark.agent_unit
def test_assert_tool_not_called_failure() -> None:
    calls = [ToolCall(server="bitbucket", name="merge_pull_request")]
    result = _result(calls)
    with pytest.raises(AssertionError, match="not to be called"):
        result.assert_tool_not_called("merge_pull_request", server="bitbucket")
