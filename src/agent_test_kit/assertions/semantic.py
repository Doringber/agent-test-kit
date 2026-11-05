"""Semantic assertions judged by TypeSafe's Jev (pytest-jev)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

# Keys tried, in order, when an agent response is a mapping.
_TEXT_KEYS = (
    "text",
    "summary",
    "message",
    "content",
    "reply",
    "suggested_prompt",
)


class SemanticJudge(Protocol):
    """The pytest-jev ``jev`` fixture: ``expect`` checks many claims in one request."""

    def expect(
        self,
        text: Any,
        *,
        holds: str | Iterable[str] = (),
        lacks: str | Iterable[str] = (),
        context: Mapping[str, Any] | None = None,
        threshold: float | None = None,
    ) -> Any:
        """Return the claims when every one passes, or raise AssertionError."""


def claim_list(claims: str | Iterable[str]) -> list[str]:
    """Normalize a single claim or a sequence of claims into a list of strings."""
    if isinstance(claims, str):
        return [claims]
    return [str(claim) for claim in claims]


def response_text(response: Any) -> str:
    """Text Jev should judge from an agent ``response`` payload.

    Strings are used as-is. Mappings prefer a known text field
    (``text``, ``summary``, ``message``, ``content``, ``reply``,
    ``suggested_prompt``). Anything else is serialized to JSON so a
    structured payload can still be judged.
    """
    if isinstance(response, str):
        if not response.strip():
            raise ValueError("agent response text is empty")
        return response
    if isinstance(response, Mapping):
        for key in _TEXT_KEYS:
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(response, sort_keys=True, ensure_ascii=False, default=str)
    if response is None:
        raise ValueError("agent response is empty; assert_means needs text to judge")
    rendered = str(response).strip()
    if not rendered:
        raise ValueError("agent response text is empty")
    return str(response)


def summarize_claims(claims: Any) -> list[dict[str, Any]]:
    """JSON-ready rows for the HTML report from a pytest-jev ``Claims`` result."""
    rows: list[dict[str, Any]] = []
    for claim in claims:
        rows.append(
            {
                "claim": getattr(claim, "claim", str(claim)),
                "expect": getattr(claim, "expect", None),
                "p": getattr(claim, "p", None),
                "passed": bool(getattr(claim, "passed", claim)),
            }
        )
    return rows
