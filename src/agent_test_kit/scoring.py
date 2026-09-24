"""Behavior scoring for agent outputs that have no single expected result."""

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent_test_kit.models.execution import AgentExecutionResult


@dataclass(frozen=True, slots=True)
class Score:
    """Normalized score in the closed interval [0.0, 1.0]."""

    value: float
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_unit_interval("score value", self.value)


@runtime_checkable
class Scorer(Protocol):
    """Scores one execution result; sync or async implementations are both accepted.

    Consumer repositories implement judgment-based scorers (LLM judge, embeddings,
    rubric review). The package ships only deterministic scorers.
    """

    name: str

    def score(self, result: AgentExecutionResult) -> Score | Awaitable[Score]:
        """Return a score for ``result``."""
        ...


async def evaluate_score(scorer: Scorer, result: AgentExecutionResult) -> Score:
    """Run a sync or async scorer and validate its return type."""
    outcome = scorer.score(result)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    if not isinstance(outcome, Score):
        raise TypeError(
            f"Scorer {scorer.name!r} must return Score. Observed: {type(outcome).__name__}"
        )
    return outcome


def validate_unit_interval(label: str, value: float) -> None:
    """Reject values outside [0.0, 1.0], including NaN and booleans."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a number between 0.0 and 1.0")
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be between 0.0 and 1.0. Observed: {value!r}")


def response_text(result: AgentExecutionResult) -> str:
    """Render ``result.response`` as text for term-based scoring."""
    response = result.response
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    return json.dumps(response, sort_keys=True, default=str, ensure_ascii=False)


class RequiredTermsScorer:
    """Fraction of required terms present in the response text."""

    def __init__(
        self,
        terms: Iterable[str],
        *,
        case_sensitive: bool = False,
        name: str = "required_terms",
    ) -> None:
        self.terms = _validated_terms(terms)
        self.case_sensitive = case_sensitive
        self.name = name

    def score(self, result: AgentExecutionResult) -> Score:
        text = _normalize(response_text(result), self.case_sensitive)
        missing = [term for term in self.terms if _normalize(term, self.case_sensitive) not in text]
        found = len(self.terms) - len(missing)
        return Score(
            found / len(self.terms),
            reason=f"Missing terms: {missing}" if missing else None,
            details={"missing": missing},
        )


class ForbiddenTermsScorer:
    """Scores 1.0 when no forbidden term appears in the response, otherwise 0.0."""

    def __init__(
        self,
        terms: Iterable[str],
        *,
        case_sensitive: bool = False,
        name: str = "forbidden_terms",
    ) -> None:
        self.terms = _validated_terms(terms)
        self.case_sensitive = case_sensitive
        self.name = name

    def score(self, result: AgentExecutionResult) -> Score:
        text = _normalize(response_text(result), self.case_sensitive)
        found = [term for term in self.terms if _normalize(term, self.case_sensitive) in text]
        return Score(
            0.0 if found else 1.0,
            reason=f"Forbidden terms present: {found}" if found else None,
            details={"found": found},
        )


class RequiredFieldsScorer:
    """Fraction of required fields present and non-null in a mapping response.

    Fields support dotted paths such as ``"order.status"``.
    """

    def __init__(self, fields: Iterable[str], *, name: str = "required_fields") -> None:
        self.fields = _validated_terms(fields)
        self.name = name

    def score(self, result: AgentExecutionResult) -> Score:
        response = result.response
        if not isinstance(response, Mapping):
            return Score(
                0.0,
                reason="Response is not a JSON object",
                details={"missing": list(self.fields)},
            )
        missing = [path for path in self.fields if _lookup(response, path) is None]
        present = len(self.fields) - len(missing)
        return Score(
            present / len(self.fields),
            reason=f"Missing fields: {missing}" if missing else None,
            details={"missing": missing},
        )


def _validated_terms(terms: Iterable[str]) -> tuple[str, ...]:
    values = tuple(terms)
    if not values:
        raise ValueError("at least one term is required")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("terms must be non-empty strings")
    return values


def _normalize(text: str, case_sensitive: bool) -> str:
    return text if case_sensitive else text.casefold()


def _lookup(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current
