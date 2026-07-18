"""Run, trace, and correlation identifiers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class RunContext:
    """Identifiers propagated through a single agent test execution."""

    run_id: str = field(default_factory=lambda: _new_id("run"))
    trace_id: str = field(default_factory=lambda: _new_id("trace"))
    correlation_id: str = field(default_factory=lambda: _new_id("corr"))
    idempotency_key: str | None = None

    def as_headers(self) -> dict[str, str]:
        headers = {
            "X-Agent-Test-Run-Id": self.run_id,
            "X-Agent-Test-Trace-Id": self.trace_id,
            "X-Agent-Test-Correlation-Id": self.correlation_id,
        }
        if self.idempotency_key:
            headers["X-Idempotency-Key"] = self.idempotency_key
        return headers

    def as_payload_metadata(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
        }
        if self.idempotency_key:
            payload["idempotency_key"] = self.idempotency_key
        return payload
