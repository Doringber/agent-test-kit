"""Redaction utility tests."""

from __future__ import annotations

import pytest

from agent_test_kit.reporting.redaction import redact_string, redact_value


@pytest.mark.agent_unit
def test_redact_bearer_token() -> None:
    value = "Authorization: Bearer abc.def.ghi"
    assert "[REDACTED]" in redact_string(value)


@pytest.mark.agent_unit
def test_redact_sensitive_keys() -> None:
    payload = {"api_token": "secret-value", "run_id": "run_123"}
    redacted = redact_value(payload)
    assert redacted["api_token"] == "[REDACTED]"
    assert redacted["run_id"] == "run_123"
