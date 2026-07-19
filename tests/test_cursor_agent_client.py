"""CursorAgentClient and stream-json trace parsing tests."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_test_kit import AgentTestConfig, CursorAgentClient
from agent_test_kit.client.cursor_trace import parse_stream_json_stdout, trace_from_cursor_response
from agent_test_kit.client.tool_inference import infer_operation_kind, infer_server
from agent_test_kit.models.enums import ToolOperationKind


@pytest.mark.agent_unit
def test_infer_server_and_operation_kind() -> None:
    assert infer_server("bitbucket_get_pullrequest_by_id") == "bitbucket"
    assert infer_server("jira_create_issue") == "jira"
    assert infer_operation_kind("bitbucket_get_diff") == ToolOperationKind.READ
    assert infer_operation_kind("jira_create_issue") == ToolOperationKind.WRITE


@pytest.mark.agent_unit
def test_parse_stream_json_stdout_extracts_tools_and_tokens() -> None:
    lines = [
        json.dumps(
            {
                "type": "tool_call",
                "subtype": "called",
                "tool_call": {
                    "mcpToolCall": {"args": {"toolName": "bitbucket_get_pullrequest_by_id"}}
                },
            }
        ),
        json.dumps({"type": "result", "usage": {"input_tokens": 100, "output_tokens": 40}}),
    ]
    trace = parse_stream_json_stdout("\n".join(lines))
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0].server == "bitbucket"
    assert trace.tool_calls[0].operation_kind == ToolOperationKind.READ
    assert trace.token_usage == 140


@pytest.mark.agent_unit
def test_trace_from_cursor_response_prefers_nested_trace() -> None:
    trace = trace_from_cursor_response(
        {
            "ok": True,
            "trace": {
                "tool_calls": [
                    {
                        "server": "bitbucket",
                        "name": "bitbucket_get_pr_diff",
                        "operation_kind": "read",
                        "output": {"authorization": "Bearer abc"},
                        "status": "success",
                    }
                ],
                "token_usage": 50,
                "model": "composer-2",
            },
        }
    )
    assert trace.tool_calls[0].name == "bitbucket_get_pr_diff"
    assert trace.tool_calls[0].output == {"authorization": "[REDACTED]"}
    assert trace.token_usage == 50
    assert trace.model == "composer-2"


class _CursorTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        body: dict[str, object] | None = None,
        *,
        status_code: int = 200,
        text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.text = text
        self.error = error
        self.last_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        if self.error is not None:
            raise self.error
        payload = json.loads(request.content.decode())
        assert payload["output_format"] == "stream-json"
        assert "prompt" in payload
        if self.text is not None:
            return httpx.Response(self.status_code, text=self.text)
        return httpx.Response(self.status_code, json=self.body)


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_cursor_agent_client_execute_prompt() -> None:
    stdout = json.dumps(
        {
            "type": "tool_call",
            "subtype": "called",
            "name": "echo",
        }
    )
    transport = _CursorTransport({"ok": True, "stdout": stdout, "stderr": ""})
    config = AgentTestConfig(
        base_url="http://qa-helper.test",
        execute_path="/agent",
        agent_id="qa-helper",
    )
    client = CursorAgentClient(config, transport=transport)
    result = await client.execute_prompt("Reply ok only.")

    result.assert_success()
    assert result.tool_calls[0].name == "echo"


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_cursor_agent_client_execute_accepts_generic_input() -> None:
    transport = _CursorTransport({"ok": True, "stdout": "", "stderr": ""})
    client = CursorAgentClient(
        AgentTestConfig(base_url="http://generic-agent.test"),
        transport=transport,
    )
    result = await client.execute({"prompt": "Summarize this input.", "mode": "ask"})

    result.assert_success()
    assert transport.last_request is not None
    assert transport.last_request.url.path == "/agent"
    payload = json.loads(transport.last_request.content.decode())
    assert payload["prompt"] == "Summarize this input."
    assert payload["mode"] == "ask"


@pytest.mark.agent_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "expected_error"),
    [
        (_CursorTransport(status_code=503, text="temporarily unavailable"), "503"),
        (_CursorTransport(text="{not-json"), "Malformed JSON"),
        (
            _CursorTransport(error=httpx.ConnectError("connection refused")),
            "Transport failure",
        ),
        (_CursorTransport(error=httpx.ReadTimeout("too slow")), "timed out"),
    ],
)
async def test_cursor_agent_client_normalizes_expected_remote_failures(
    transport: _CursorTransport,
    expected_error: str,
) -> None:
    client = CursorAgentClient(
        AgentTestConfig(base_url="http://generic-agent.test"),
        transport=transport,
    )
    context = client.new_run_context()

    result = await client.execute("Reply with ok.", run_context=context)

    assert not result.success
    assert expected_error.lower() in (result.error or "").lower()
    assert result.correlation_id == context.correlation_id


@pytest.mark.agent_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_event",
    [
        {"type": "tool_call", "subtype": "called", "tool_call": "invalid"},
        {
            "type": "tool_call",
            "subtype": "called",
            "tool_call": {"mcpToolCall": ["invalid"]},
        },
    ],
)
async def test_cursor_agent_client_normalizes_malformed_tool_payloads(
    malformed_event: dict[str, object],
) -> None:
    transport = _CursorTransport(
        {
            "ok": True,
            "stdout": json.dumps(malformed_event),
            "stderr": "",
        }
    )
    client = CursorAgentClient(
        AgentTestConfig(base_url="http://generic-agent.test"),
        transport=transport,
    )
    context = client.new_run_context()

    result = await client.execute("Reply with ok.", run_context=context)

    assert not result.success
    assert "malformed cursor agent response" in (result.error or "").lower()
    assert result.run_id == context.run_id
    assert result.correlation_id == context.correlation_id


@pytest.mark.agent_unit
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tool_calls", "events"])
async def test_cursor_agent_client_normalizes_malformed_nested_trace_collections(
    field: str,
) -> None:
    transport = _CursorTransport(
        {
            "ok": True,
            "trace": {field: {"invalid": "mapping"}},
            "stderr": "",
        }
    )
    client = CursorAgentClient(
        AgentTestConfig(base_url="http://generic-agent.test"),
        transport=transport,
    )
    context = client.new_run_context()

    result = await client.execute("Reply with ok.", run_context=context)

    assert not result.success
    assert f"trace.{field} must be a list" in (result.error or "")
    assert result.run_id == context.run_id
    assert result.correlation_id == context.correlation_id
