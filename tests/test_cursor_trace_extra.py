"""Additional coverage for cursor trace and tool inference."""

from __future__ import annotations

import json

import pytest

from agent_test_kit.client.cursor_trace import parse_stream_json_stdout, trace_from_cursor_response
from agent_test_kit.client.tool_inference import infer_operation_kind, infer_server
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind


@pytest.mark.agent_unit
def test_infer_server_mcp_prefix() -> None:
    assert infer_server("mcp__bitbucket__get_pr") == "bitbucket"


@pytest.mark.agent_unit
def test_trace_from_tools_called_list() -> None:
    trace = trace_from_cursor_response(
        {"ok": True, "tools_called": ["bitbucket_list_branches", "jira_get_issue"]}
    )
    assert len(trace.tool_calls) == 2
    assert trace.tool_calls[0].server == "bitbucket"


@pytest.mark.agent_unit
def test_infer_operation_unknown() -> None:
    assert infer_operation_kind("custom_tool") == ToolOperationKind.UNKNOWN


@pytest.mark.agent_unit
def test_explicit_tool_metadata_mappings_override_heuristics() -> None:
    trace = parse_stream_json_stdout(
        '{"type":"tool_call","subtype":"called","id":"1","name":"custom_lookup"}',
        server_mappings={"custom_lookup": "inventory"},
        operation_mappings={"custom_lookup": ToolOperationKind.WRITE},
    )

    assert trace.tool_calls[0].server == "inventory"
    assert trace.tool_calls[0].operation_kind == ToolOperationKind.WRITE


@pytest.mark.agent_unit
def test_unknown_tool_operation_remains_conservative_in_read_only_sequence() -> None:
    trace = trace_from_cursor_response({"tools_called": ["custom_action"]})

    assert trace.tool_calls[0].operation_kind == ToolOperationKind.UNKNOWN
    with pytest.raises(AssertionError, match="Unexpected non-read tool"):
        from agent_test_kit.models.execution import AgentExecutionResult

        AgentExecutionResult(success=True, run_id="run", trace=trace).assert_tool_sequence(
            [("bitbucket", "get_pull_request")],
            allow_additional_read_tools=True,
        )


@pytest.mark.agent_unit
def test_stream_events_correlate_calls_and_preserve_metadata() -> None:
    events = [
        {
            "type": "tool_call",
            "subtype": "called",
            "id": "call-1",
            "server": "bitbucket-platform",
            "timestamp": "2026-07-18T10:00:00Z",
            "attempt": 2,
            "parent_step_id": "step-7",
            "tool_call": {
                "mcpToolCall": {
                    "args": {
                        "toolName": "bitbucket_get_pr",
                        "arguments": {"pull_request_id": 125},
                    }
                }
            },
        },
        {
            "type": "tool_call",
            "subtype": "completed",
            "id": "call-1",
            "status": "success",
            "timestamp": "2026-07-18T10:00:01Z",
            "output": {"api_token": "secret", "title": "Fix"},
        },
        {
            "type": "tool_call",
            "subtype": "called",
            "id": "call-2",
            "name": "jira_create_issue",
        },
        {
            "type": "tool_call",
            "subtype": "completed",
            "id": "call-2",
            "status": "error",
            "error": "permission denied",
        },
        {
            "type": "tool_call",
            "subtype": "called",
            "id": "call-3",
            "name": "custom_pending_action",
        },
        {
            "type": "result",
            "model": "composer-2",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    ]

    trace = parse_stream_json_stdout("\n".join(json.dumps(event) for event in events))

    assert len(trace.tool_calls) == 3
    completed, failed, incomplete = trace.tool_calls
    assert completed.id == "call-1"
    assert completed.server == "bitbucket-platform"
    assert completed.arguments == {"pull_request_id": 125}
    assert completed.output == {"api_token": "[REDACTED]", "title": "Fix"}
    assert completed.status == ToolCallStatus.SUCCESS
    assert completed.duration_ms == 1000
    assert completed.attempt == 2
    assert completed.parent_step_id == "step-7"
    assert failed.status == ToolCallStatus.ERROR
    assert failed.output == "permission denied"
    assert incomplete.status != ToolCallStatus.SUCCESS
    assert trace.token_usage == 120
    assert trace.model == "composer-2"


@pytest.mark.agent_unit
def test_nested_trace_without_status_is_not_assumed_successful() -> None:
    trace = trace_from_cursor_response(
        {"trace": {"tool_calls": [{"id": "pending-1", "name": "custom_action"}]}}
    )

    assert trace.tool_calls[0].status != ToolCallStatus.SUCCESS


@pytest.mark.agent_unit
def test_completed_mcp_result_with_nested_error_is_not_successful() -> None:
    events = [
        {
            "type": "tool_call",
            "subtype": "called",
            "id": "nested-failure",
            "tool_call": {
                "mcpToolCall": {
                    "args": {
                        "serverName": "jira-production",
                        "toolName": "jira_create_issue",
                        "arguments": {"summary": "Bug"},
                    }
                }
            },
        },
        {
            "type": "tool_call",
            "subtype": "completed",
            "id": "nested-failure",
            "tool_call": {
                "mcpToolCall": {"result": {"isError": True, "error": "permission denied"}}
            },
        },
    ]

    trace = parse_stream_json_stdout("\n".join(json.dumps(event) for event in events))

    assert trace.tool_calls[0].server == "jira-production"
    assert trace.tool_calls[0].status == ToolCallStatus.ERROR


@pytest.mark.agent_unit
def test_stream_event_arguments_are_redacted_recursively() -> None:
    event = {
        "type": "tool_call",
        "subtype": "called",
        "name": "custom_action",
        "arguments": {
            "api_key": "secret-key",
            "nested": {"authorization": "Bearer abc.def", "safe": "value"},
        },
    }

    trace = parse_stream_json_stdout(json.dumps(event))

    assert trace.tool_calls[0].arguments == {
        "api_key": "[REDACTED]",
        "nested": {"authorization": "[REDACTED]", "safe": "value"},
    }


@pytest.mark.agent_unit
def test_nested_trace_is_fully_redacted_and_mappings_fill_unknown_metadata() -> None:
    trace = trace_from_cursor_response(
        {
            "trace": {
                "tool_calls": [
                    {
                        "name": "custom_action",
                        "arguments": {"password": "secret", "safe": "value"},
                        "output": {"credential": "secret"},
                        "operation_kind": "unknown",
                    }
                ],
                "events": [
                    {
                        "timestamp": "2026-07-18T10:00:00Z",
                        "label": "tool",
                        "event_type": "tool_call",
                        "metadata": {"api_token": "secret", "safe": "value"},
                    }
                ],
                "token_usage": 25,
            }
        },
        server_mappings={"custom_action": "custom-server"},
        operation_mappings={"custom_action": ToolOperationKind.WRITE},
    )

    tool_call = trace.tool_calls[0]
    assert tool_call.server == "custom-server"
    assert tool_call.operation_kind == ToolOperationKind.WRITE
    assert tool_call.arguments == {"password": "[REDACTED]", "safe": "value"}
    assert tool_call.output == {"credential": "[REDACTED]"}
    assert trace.events[0].metadata == {"api_token": "[REDACTED]", "safe": "value"}
    assert trace.token_usage == 25


@pytest.mark.agent_unit
def test_nested_trace_mapping_replaces_unknown_server() -> None:
    trace = trace_from_cursor_response(
        {
            "trace": {
                "tool_calls": [
                    {
                        "name": "custom_action",
                        "server": "unknown",
                        "operation_kind": "read",
                    }
                ]
            }
        },
        server_mappings={"custom_action": "custom-server"},
    )

    assert trace.tool_calls[0].server == "custom-server"


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"total_tokens": 42}, 42),
        ({"totalTokens": 43}, 43),
    ],
)
def test_stream_result_extracts_explicit_total_tokens(
    usage: dict[str, int],
    expected: int,
) -> None:
    trace = parse_stream_json_stdout(json.dumps({"type": "result", "usage": usage}))

    assert trace.token_usage == expected


@pytest.mark.agent_unit
@pytest.mark.parametrize("field", ["tool_calls", "events"])
def test_nested_trace_collections_must_be_lists(field: str) -> None:
    with pytest.raises(ValueError, match=rf"trace\.{field} must be a list"):
        trace_from_cursor_response({"trace": {field: {"invalid": "mapping"}}})


@pytest.mark.agent_unit
def test_stream_extracts_current_cursor_nested_mcp_arguments() -> None:
    event = {
        "type": "tool_call",
        "subtype": "started",
        "tool_call": {
            "toolCallId": "toolu_123",
            "mcpToolCall": {
                "args": {
                    "serverIdentifier": "bitbucket",
                    "toolName": "bitbucket_get_pullrequest_by_id",
                    "args": {
                        "workspace": "acme_dev",
                        "repo_slug": "agent-qa-helper",
                        "pullrequest_id": 29,
                    },
                }
            },
        },
    }

    trace = parse_stream_json_stdout(json.dumps(event))

    assert trace.tool_calls[0].server == "bitbucket"
    assert trace.tool_calls[0].name == "bitbucket_get_pullrequest_by_id"
    assert trace.tool_calls[0].arguments == {
        "workspace": "acme_dev",
        "repo_slug": "agent-qa-helper",
        "pullrequest_id": 29,
    }
