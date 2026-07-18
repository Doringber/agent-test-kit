"""RunContext tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.run_context import RunContext


@pytest.mark.agent_unit
def test_run_context_generates_ids() -> None:
    context = RunContext()
    assert context.run_id.startswith("run_")
    assert context.trace_id.startswith("trace_")
    assert context.correlation_id.startswith("corr_")


@pytest.mark.agent_unit
def test_run_context_headers_and_metadata() -> None:
    context = RunContext(idempotency_key="idem-123")
    headers = context.as_headers()
    assert headers["X-Agent-Test-Run-Id"] == context.run_id
    assert headers["X-Idempotency-Key"] == "idem-123"
    metadata = context.as_payload_metadata()
    assert metadata["correlation_id"] == context.correlation_id
