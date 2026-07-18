"""Redact sensitive values from reports and logs."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|authorization|api[_-]?key|credential)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


def redact_string(value: str) -> str:
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    if len(redacted) > 8 and _SENSITIVE_KEY_PATTERN.search(redacted):
        return "[REDACTED]"
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY_PATTERN.search(str(key)):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_value(item)
        return result
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value
