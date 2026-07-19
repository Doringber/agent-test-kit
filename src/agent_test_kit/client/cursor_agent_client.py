"""HTTP client for Pango Cursor agent-base /agent endpoints."""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.client.cursor_trace import trace_from_cursor_response
from agent_test_kit.client.result_normalization import (
    ResultCallback,
    complete_result,
    failed_result,
    http_error_message,
    response_body,
)
from agent_test_kit.models.execution import AgentExecutionResult, utc_now
from agent_test_kit.models.run_context import RunContext


class CursorAgentClient:
    """Execute real Cursor agents via POST /agent and normalize traces."""

    def __init__(
        self,
        config: AgentTestConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        on_result: ResultCallback | None = None,
    ) -> None:
        base_config = config or AgentTestConfig(output_format="stream-json")
        self.config = base_config.model_copy(update={"execute_path": "/agent"})
        self._transport = transport
        self._on_result = on_result

    def new_run_context(self, *, idempotency_key: str | None = None) -> RunContext:
        context = RunContext()
        if idempotency_key is not None:
            context.idempotency_key = idempotency_key
        return context

    async def execute_prompt(
        self,
        prompt: str,
        *,
        run_context: RunContext | None = None,
        mode: str = "agent",
        output_format: str | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentExecutionResult:
        context = run_context or self.new_run_context()
        started_at = utc_now()
        payload: dict[str, Any] = {
            "prompt": prompt,
            "mode": mode,
            "output_format": output_format or self.config.output_format,
            "timeout_s": int(timeout_seconds or self.config.timeout_seconds),
        }
        headers = context.as_headers()
        timeout = httpx.Timeout(timeout_seconds or self.config.timeout_seconds)

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                response = await client.post(
                    self.config.execute_url,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Cursor agent request timed out: {exc}",
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

        success = bool(body.get("ok", False)) and response.status_code < 400
        try:
            trace = trace_from_cursor_response(
                body,
                server_mappings=self.config.tool_server_mappings,
                operation_mappings=self.config.tool_operation_mappings,
            )
        except ValueError as exc:
            return failed_result(
                context=context,
                started_at=started_at,
                error=f"Malformed Cursor agent response: {exc}",
                response=body,
                callback=self._on_result,
            )
        run_id = str(body.get("run_id") or context.run_id)
        error = body.get("error") or body.get("stderr")
        if not success and not error:
            error = "Cursor agent returned an unsuccessful response"

        result = AgentExecutionResult(
            success=success,
            run_id=run_id,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
            response=body,
            error=str(error) if error else None,
            trace=trace,
            started_at=started_at,
        )
        return complete_result(result, callback=self._on_result)

    async def execute(
        self,
        input: dict[str, Any] | str,
        *,
        run_context: RunContext | None = None,
        prompt: str | None = None,
    ) -> AgentExecutionResult:
        """Execute a generic prompt or structured input against Cursor /agent."""
        options = input if isinstance(input, dict) else {}
        resolved_prompt = prompt
        if resolved_prompt is None and isinstance(input, str):
            resolved_prompt = input
        if resolved_prompt is None:
            candidate = options.get("prompt") or options.get("input")
            if isinstance(candidate, str):
                resolved_prompt = candidate
            else:
                resolved_prompt = json.dumps(input, sort_keys=True)
        return await self.execute_prompt(
            resolved_prompt,
            run_context=run_context,
            mode=str(options.get("mode", "agent")),
            output_format=options.get("output_format"),
            timeout_seconds=options.get("timeout_seconds"),
        )
