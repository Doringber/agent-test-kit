"""Built-in guardrails for assistant language and required final tool calls."""

from __future__ import annotations

import re
from collections.abc import Iterable

from agent_test_kit.guardrails.base import Guardrail
from agent_test_kit.models.execution import AgentExecutionResult

_DEFAULT_PROFANITY: tuple[str, ...] = (
    "fuck",
    "fucking",
    "fucked",
    "shit",
    "shitty",
    "bitch",
    "asshole",
    "bastard",
    "dick",
    "piss",
)


class NoProfanityGuardrail(Guardrail):
    """Reject disallowed language in assistant output.

    The default term list is a small profanity set. Pass ``terms`` to replace it
    with any disallowed language, or ``extra_terms`` to add phrases. Matching is
    case-insensitive. A single word uses word boundaries; a phrase matches as text.
    """

    def __init__(
        self,
        terms: Iterable[str] | None = None,
        *,
        extra_terms: Iterable[str] = (),
        name: str = "no_profanity",
    ) -> None:
        selected = tuple(terms) if terms is not None else _DEFAULT_PROFANITY
        combined = _validated_terms((*selected, *extra_terms))
        self.terms = combined
        self._compiled = tuple(_compile_term(term) for term in combined)
        self.name = name

    def on_message(self, text: str, *, role: str = "assistant") -> str | None:
        if role != "assistant" or not text:
            return None
        found = _find_terms(text, self.terms, self._compiled)
        if not found:
            return None
        return f"Disallowed language in assistant output: {', '.join(found)}"


class RequiredFinalToolGuardrail(Guardrail):
    """The run must finish with a successful call to ``tool_name``.

    Use this for flow rules such as "this agent must open a pull request at the end".
    The check runs on the finished trace, offline or when an online monitor finishes.
    """

    def __init__(
        self,
        tool_name: str,
        *,
        server: str | None = None,
        name: str | None = None,
        require_success: bool = True,
    ) -> None:
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool_name must be a non-empty string")
        self.tool_name = tool_name
        self.server = server
        self.require_success = require_success
        self.name = name or "required_final_tool"

    def on_trace(self, result: AgentExecutionResult) -> str | None:
        expected = _qualified(self.server, self.tool_name)
        calls = result.tool_calls
        if not calls:
            return f"Expected final tool {expected}; the run recorded no tool calls"
        last = calls[-1]
        if not last.matches(self.tool_name, self.server):
            return f"Expected final tool {expected}; observed {_qualified(last.server, last.name)}"
        if self.require_success and not last.is_success:
            status = last.status.value if hasattr(last.status, "value") else str(last.status)
            return f"Final tool {expected} finished with status {status}"
        return None


def must_open_pull_request(
    tool_name: str = "create_pull_request",
    *,
    server: str | None = None,
) -> RequiredFinalToolGuardrail:
    """Flow rule: the agent must open a pull request as its final tool call."""
    return RequiredFinalToolGuardrail(
        tool_name,
        server=server,
        name="must_open_pull_request",
    )


def _validated_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise ValueError("disallowed terms must be non-empty strings")
        if term not in unique:
            unique.append(term)
    if not unique:
        raise ValueError("at least one disallowed term is required")
    return tuple(unique)


def _compile_term(term: str) -> tuple[str, re.Pattern[str] | None]:
    needle = term.casefold()
    if any(character.isspace() for character in needle) or not needle.isalnum():
        return needle, None
    return needle, re.compile(rf"\b{re.escape(needle)}\b")


def _find_terms(
    text: str,
    terms: tuple[str, ...],
    compiled: tuple[tuple[str, re.Pattern[str] | None], ...],
) -> list[str]:
    folded = text.casefold()
    found: list[str] = []
    for original, (needle, pattern) in zip(terms, compiled, strict=True):
        matched = needle in folded if pattern is None else pattern.search(folded) is not None
        if matched:
            found.append(original)
    return found


def _qualified(server: str | None, tool_name: str) -> str:
    if server:
        return f"{server}/{tool_name}"
    return tool_name
