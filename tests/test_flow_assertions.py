"""Flow assertion engine tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace


def _result_with_calls(calls: list[ToolCall]) -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="run_test",
        trace=AgentTrace(tool_calls=calls),
    )


@pytest.mark.agent_unit
def test_assert_tool_called(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_tool_called("get_pull_request", server="bitbucket")


@pytest.mark.agent_unit
def test_assert_tool_not_called(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_tool_not_called("merge_pull_request", server="bitbucket")


@pytest.mark.agent_unit
def test_assert_tool_called_failure() -> None:
    result = _result_with_calls([])
    with pytest.raises(AssertionError, match="Expected tool"):
        result.assert_tool_called("missing_tool")


@pytest.mark.agent_unit
def test_assert_tool_order(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_tool_order(
        before=("bitbucket", "get_pull_request"),
        after=("bitbucket", "get_diff"),
    )


@pytest.mark.agent_unit
def test_assert_tool_sequence_exact(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_tool_sequence(
        [
            ("bitbucket", "get_pull_request"),
            ("bitbucket", "get_diff"),
            ("jira", "create_issue"),
            ("bitbucket", "add_comment"),
        ]
    )


@pytest.mark.agent_unit
def test_assert_read_before_write(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_read_before_write(
        read_tool=("bitbucket", "get_diff"),
        write_tool=("jira", "create_issue"),
    )


@pytest.mark.agent_unit
def test_assert_no_duplicate_tool_writes() -> None:
    calls = [
        ToolCall(server="jira", name="create_issue", operation_kind=ToolOperationKind.WRITE),
        ToolCall(server="jira", name="create_issue", operation_kind=ToolOperationKind.WRITE),
    ]
    result = _result_with_calls(calls)
    with pytest.raises(AssertionError, match="Duplicate write"):
        result.assert_no_duplicate_tool_writes()


@pytest.mark.agent_unit
def test_assert_write_tool_called_once(sample_tool_calls: list[ToolCall]) -> None:
    result = _result_with_calls(sample_tool_calls)
    result.assert_write_tool_called_once(server="jira", tool="create_issue")
