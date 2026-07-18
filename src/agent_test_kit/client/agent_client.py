"""REST client for executing agents under test."""

from __future__ import annotations

from typing import Any

import httpx

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult, utc_now
from agent_test_kit.models.run_context import RunContext


class AgentClient:
    """HTTP client that executes an agent and returns normalized results."""

    def __init__(
        self,
        config: AgentTestConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or AgentTestConfig()
        self._transport = transport

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

        async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
            response = await client.post(
                self.config.execute_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()

        completed_at = utc_now()
        result = AgentExecutionResult.from_api_response(body, run_context=context)
        if result.started_at is None:
            result.started_at = started_at
        if result.completed_at is None:
            result.completed_at = completed_at
        if result.duration_ms is None and result.started_at and result.completed_at:
            delta = result.completed_at - result.started_at
            result.duration_ms = int(delta.total_seconds() * 1000)
        return result
