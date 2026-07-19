"""Shared normalization helpers for remote agent responses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from agent_test_kit.models.execution import AgentExecutionResult, utc_now
from agent_test_kit.models.run_context import RunContext
from agent_test_kit.models.trace import AgentTrace

ResultCallback = Callable[[AgentExecutionResult], None]


def complete_result(
    result: AgentExecutionResult, *, callback: ResultCallback | None
) -> AgentExecutionResult:
    """Populate timing information and notify an optional result observer."""
    if result.completed_at is None:
        result.completed_at = utc_now()
    if result.duration_ms is None and result.started_at is not None:
        delta = result.completed_at - result.started_at
        result.duration_ms = int(delta.total_seconds() * 1000)
    if callback is not None:
        callback(result)
    return result


def failed_result(
    *,
    context: RunContext,
    started_at: datetime,
    error: str,
    response: Any | None = None,
    trace: AgentTrace | None = None,
    callback: ResultCallback | None = None,
) -> AgentExecutionResult:
    """Create a correlated failed result instead of leaking remote errors."""
    return complete_result(
        AgentExecutionResult(
            success=False,
            run_id=context.run_id,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
            response=response,
            error=error,
            trace=trace or AgentTrace(),
            started_at=started_at,
        ),
        callback=callback,
    )


def response_body(response: httpx.Response) -> tuple[dict[str, Any] | None, str | None]:
    """Decode an object response, retaining useful text for malformed payloads."""
    if not response.content:
        return {}, None
    try:
        payload = response.json()
    except ValueError:
        return None, response.text
    if not isinstance(payload, dict):
        return None, response.text
    return payload, None


def http_error_message(
    response: httpx.Response,
    body: dict[str, Any] | None,
    fallback_text: str | None,
) -> str:
    """Build a stable HTTP failure message without exposing an exception."""
    detail: Any | None = None
    if body is not None:
        detail = body.get("error") or body.get("detail") or body.get("stderr")
    detail = detail or fallback_text or response.reason_phrase
    return f"HTTP {response.status_code}: {detail}"
