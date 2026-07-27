"""Redact sensitive values from reports and logs."""

from __future__ import annotations

import re
from typing import Any

_BEARER_PATTERN = re.compile(
    r"\bBearer\s+"
    r"(?!(?:token|tokens|authentication|authorization|credential|credentials|scheme|flow)\b)"
    r"[A-Za-z0-9\-._~+/]{8,}=*",
    re.IGNORECASE,
)


def _credential_key_pattern() -> str:
    """Build a string pattern from the shared key classifier."""
    return (
        r"(?:"
        r"(?:[A-Za-z0-9]+[_-])*(?:token|secret|password|authorization|credentials?)"
        r"|(?:[A-Za-z0-9]+[_-])*api[_ -]?key"
        r"|authorization[_-]header"
        r"|(?:[A-Za-z0-9]+(?:[A-Z][a-z0-9]*)*)?"
        r"(?:apiToken|accessToken|refreshToken|authToken|bearerToken|idToken|clientSecret|"
        r"ApiKey|AccessToken|RefreshToken|AuthToken|BearerToken|IdToken|ClientSecret|SecretKey)"
        r")"
    )


_CREDENTIAL_KEY = _credential_key_pattern()
_QUOTED_CREDENTIAL_FIELD_PATTERN = re.compile(
    rf"""(?P<prefix>
        (?<![\w-])
        ["']?{_CREDENTIAL_KEY}["']?
        \s*[:=]\s*
    )
    (?P<quote>["'])
    (?P<value>
        (?:\\[^\r\n]|(?!(?P=quote))[^\r\n\\])*
    )
    (?P=quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UNQUOTED_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    rf"""(?P<prefix>
        (?<![\w-])
        {_CREDENTIAL_KEY}
        \s*[:=]\s*
    )
    (?P<scheme>(?:Bearer|Basic|Digest|Token)\s+)?
    (?P<value>[^"'()\s,;}}\]\r\n]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CAMEL_ACRONYM_BOUNDARY_PATTERN = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY_PATTERN = re.compile(r"([a-z0-9])([A-Z])")
_KEY_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_TOKEN_USAGE_KEYS = {
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "input_tokens",
    "output_tokens",
    "token_usage",
    "total_input_tokens",
    "total_output_tokens",
    "total_token_usage",
    "total_tokens",
}
_SENSITIVE_TERMINAL_SEGMENTS = {
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
_SENSITIVE_EXACT_KEYS = {"apikey"}
_SENSITIVE_SUFFIXES = {
    ("api", "key"),
    ("auth", "header"),
    ("authorization", "header"),
    ("secret", "access", "key"),
    ("access", "key"),
    ("access", "token"),
    ("refresh", "token"),
    ("client", "secret"),
    ("auth", "token"),
    ("id", "token"),
    ("bearer", "token"),
}

# Avoid ReDoS on huge stream-json stdout (credential regex is exponential on long runs).
_MAX_REDACT_LINE_CHARS = 8_192
_MAX_REDACT_STRING_CHARS = 262_144
_CREDENTIAL_HINT = re.compile(
    r"(?i)(?:api[_ -]?key|(?:access|refresh|auth|id|bearer)[_-]?token|"
    r"client[_-]?secret|authorization|credentials?|password|secret|bearer\s+)",
)


def _redact_quoted_field(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{match.group('quote')}[REDACTED]{match.group('quote')}"


def _redact_unquoted_field(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{match.group('scheme') or ''}[REDACTED]"


def _normalized_key_segments(key: str) -> tuple[str, ...]:
    with_acronym_boundaries = _CAMEL_ACRONYM_BOUNDARY_PATTERN.sub(r"\1_\2", key)
    with_word_boundaries = _CAMEL_WORD_BOUNDARY_PATTERN.sub(
        r"\1_\2",
        with_acronym_boundaries,
    )
    return tuple(
        segment for segment in _KEY_SEPARATOR_PATTERN.split(with_word_boundaries.lower()) if segment
    )


def _is_sensitive_key(key: str) -> bool:
    segments = _normalized_key_segments(key)
    normalized = "_".join(segments)
    if normalized in _TOKEN_USAGE_KEYS:
        return False
    if normalized in _SENSITIVE_EXACT_KEYS:
        return True
    if segments and segments[-1] in _SENSITIVE_TERMINAL_SEGMENTS:
        return True
    if any(
        segments[-len(suffix) :] == suffix
        for suffix in _SENSITIVE_SUFFIXES
        if len(segments) >= len(suffix)
    ):
        return True
    # Match compound credential suffixes anywhere in the key, not only at the end.
    for index in range(len(segments)):
        for suffix in _SENSITIVE_SUFFIXES:
            if segments[index : index + len(suffix)] == suffix:
                return True
    return False


def _redact_string_chunk(value: str) -> str:
    redacted = _QUOTED_CREDENTIAL_FIELD_PATTERN.sub(_redact_quoted_field, value)
    redacted = _UNQUOTED_CREDENTIAL_ASSIGNMENT_PATTERN.sub(
        _redact_unquoted_field,
        redacted,
    )
    return _BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)


def _redact_bounded_line(line: str) -> str:
    if len(line) > _MAX_REDACT_LINE_CHARS:
        line = line[:_MAX_REDACT_LINE_CHARS] + "...[truncated for redaction]"
    if not _CREDENTIAL_HINT.search(line):
        return line
    return _redact_string_chunk(line)


def redact_string(value: str) -> str:
    if len(value) > _MAX_REDACT_STRING_CHARS:
        value = value[:_MAX_REDACT_STRING_CHARS] + "\n...[truncated for redaction]"

    if len(value) <= _MAX_REDACT_LINE_CHARS:
        return _redact_string_chunk(value)

    if "\n" in value:
        return "\n".join(_redact_bounded_line(line) for line in value.split("\n"))

    # Single-line blob (e.g. minified JSON) — process in fixed-size chunks.
    chunks = [
        _redact_bounded_line(value[index : index + _MAX_REDACT_LINE_CHARS])
        for index in range(0, len(value), _MAX_REDACT_LINE_CHARS)
    ]
    return "".join(chunks)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_value(item)
        return result
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value
