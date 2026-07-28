"""REST client for executing agents under test."""

from __future__ import annotations

from typing import Any

import httpx

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.client.result_normalization import (
    ResultCallback,
    complete_result,
    failed_result,
    http_error_message,
    response_body,
)
from agent_test_kit.models.execution import AgentExecutionResult, utc_now
from agent_test_kit.models.run_context import RunContext


class AgentClient:
    """HTTP client that executes an agent and returns normalized results."""

    def __init__(
        self,
        config: AgentTestConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        on_result: ResultCallback | None = None,
    ) -> None:
        self.config = config or AgentTestConfig()
        self._transport = transport
        self._on_result = on_result

    def new_run_context(self, *, idempotency_key: str | None = None) -> RunContext:
        context = RunContext()
        if idempotency_key is not None:
            context.idempotency_key = idempotency_key
        return context

    async def execute(
        self,
        input: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        context = run_context or self.new_run_context()
        started_at = utc_now()
        payload = {
            "input": input,
            "metadata": context.as_payload_metadata(),
            "agent_id": self.config.agent_id,
        }
        headers = context.as_headers()
        timeout = httpx.Timeout(self.config.timeout_seconds)

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                verify=self.config.verify_ssl,
            ) as client:
                response = await client.post(
                    self.config.execute_url,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Agent request timed out: {exc}",
                callback=self._on_result,
            )
        except httpx.TransportError as exc:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Transport failure: {exc}",
                callback=self._on_result,
            )

        body, invalid_text = response_body(response)
        if response.is_error:
            return failed_result(
                context=context,
                started_at=started_at,
                error=http_error_message(response, body, invalid_text),
                response=body if body is not None else invalid_text,
                callback=self._on_result,
            )
        if body is None:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Malformed JSON response: {invalid_text or 'invalid response body'}",
                response=invalid_text,
                callback=self._on_result,
            )
        try:
            result = AgentExecutionResult.from_api_response(body, run_context=context)
        except ValueError as exc:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Malformed agent response: {exc}",
                response=body,
                callback=self._on_result,
            )
        if result.started_at is None:
            result.started_at = started_at
        return complete_result(result, callback=self._on_result)
