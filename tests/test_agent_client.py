"""AgentClient REST execution tests."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_test_kit import AgentClient, AgentTestConfig
from agent_test_kit.models.enums import ToolOperationKind


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        response_body: dict[str, object] | None = None,
        *,
        status_code: int = 200,
        text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response_body = response_body
        self.status_code = status_code
        self.text = text
        self.error = error
        self.last_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        if self.error is not None:
            raise self.error
        if self.text is not None:
            return httpx.Response(self.status_code, text=self.text)
        return httpx.Response(self.status_code, json=self.response_body)


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_execute_parses_response_and_propagates_context() -> None:
    body = {
        "success": True,
        "response": {"summary": "done"},
        "trace": {
            "tool_calls": [
                {
                    "server": "bitbucket",
                    "name": "get_pull_request",
                    "operation_kind": "read",
                }
            ]
        },
    }
    transport = _MockTransport(body)
    config = AgentTestConfig(base_url="http://agent.test", agent_id="pr-reviewer")
    client = AgentClient(config, transport=transport)
    context = client.new_run_context(idempotency_key="idem-1")

    result = await client.execute(
        {"repository": "test-repository", "pull_request_id": 125},
        run_context=context,
    )

    assert result.success
    assert result.run_id == context.run_id
    assert result.tool_calls[0].server == "bitbucket"
    assert result.tool_calls[0].operation_kind == ToolOperationKind.READ
    assert transport.last_request is not None
    payload = json.loads(transport.last_request.content.decode())
    assert payload["metadata"]["correlation_id"] == context.correlation_id
    assert transport.last_request.headers["X-Idempotency-Key"] == "idem-1"


@pytest.mark.agent_unit
def test_new_run_context_generates_unique_ids() -> None:
    client = AgentClient(AgentTestConfig())
    first = client.new_run_context()
    second = client.new_run_context()
    assert first.run_id != second.run_id


@pytest.mark.agent_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "expected_error"),
    [
        (_MockTransport(status_code=500, text="server exploded"), "500"),
        (_MockTransport(text="<html>not json</html>"), "Malformed JSON"),
        (_MockTransport(error=httpx.ConnectError("connection refused")), "Transport failure"),
        (_MockTransport(error=httpx.ReadTimeout("too slow")), "timed out"),
    ],
)
async def test_execute_normalizes_expected_remote_failures(
    transport: _MockTransport,
    expected_error: str,
) -> None:
    client = AgentClient(
        AgentTestConfig(base_url="http://agent.test"),
        transport=transport,
    )
    context = client.new_run_context()

    result = await client.execute({"message": "hello"}, run_context=context)

    assert not result.success
    assert expected_error.lower() in (result.error or "").lower()
    assert result.run_id == context.run_id
    assert result.correlation_id == context.correlation_id
