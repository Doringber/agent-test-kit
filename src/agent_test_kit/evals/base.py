"""Evals: named scores with a pass threshold, registered and run from pytest."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.scoring import Score, validate_unit_interval

_REGISTRY: dict[str, Eval] = {}


@dataclass(frozen=True, slots=True)
class EvalResult:
    """Score and pass/fail outcome for one eval on one run."""

    name: str
    passed: bool
    score: float
    threshold: float
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def assert_passed(self) -> None:
        if self.passed:
            return
        detail = f" ({self.reason})" if self.reason else ""
        raise AssertionError(
            f"Eval {self.name!r} failed: score {self.score:.2f} "
            f"is below {self.threshold:.2f}{detail}"
        )


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Aggregate of every eval run together."""

    results: tuple[EvalResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def assert_passed(self) -> None:
        failures = [result for result in self.results if not result.passed]
        if not failures:
            return
        lines = []
        for result in failures:
            detail = f" ({result.reason})" if result.reason else ""
            lines.append(
                f"{result.name}: score {result.score:.2f} is below {result.threshold:.2f}{detail}"
            )
        raise AssertionError("Eval failures:\n" + "\n".join(lines))


class Eval:
    """Score one execution result. Pass when ``score >= threshold``.

    Subclass and implement ``score``, or build one with ``@eval_case``.
    ``score`` may return a ``Score``, a float in ``[0.0, 1.0]``, or a bool.
    """

    name: str = "eval"
    threshold: float = 1.0

    def __init__(self, *, name: str | None = None, threshold: float = 1.0) -> None:
        if name is not None:
            self.name = name
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("eval name must be a non-empty string")
        validate_unit_interval(f"eval {self.name} threshold", threshold)
        self.threshold = threshold

    def score(self, result: AgentExecutionResult) -> Score | float | bool:
        """Return a score for ``result``."""
        raise NotImplementedError

    def evaluate(self, result: AgentExecutionResult) -> EvalResult:
        """Score ``result`` and compare it to the threshold."""
        raw = self.score(result)
        if inspect.isawaitable(raw):
            close = getattr(raw, "close", None)
            if close is not None:
                close()
            raise TypeError(
                f"Eval {self.name!r} returned an awaitable. "
                "score() must be synchronous and return a Score, float, or bool."
            )
        value, reason, details = _coerce_score(self.name, raw)
        passed = value >= self.threshold
        if reason is None and not passed:
            reason = f"score {value:.2f} is below {self.threshold:.2f}"
        return EvalResult(
            name=self.name,
            passed=passed,
            score=value,
            threshold=self.threshold,
            reason=reason,
            details=details,
        )

    def __call__(self, result: AgentExecutionResult) -> EvalResult:
        return self.evaluate(result)


def run_evals(
    result: AgentExecutionResult,
    evals: Eval | Sequence[Eval],
) -> EvalReport:
    """Score ``result`` with each eval. Does not raise; call ``assert_passed``."""
    selected = _as_evals(evals)
    return EvalReport(tuple(item.evaluate(result) for item in selected))


def register_eval(evaluation: Eval) -> Eval:
    """Register ``evaluation`` under its name. Registering the same object twice is a no-op."""
    if not isinstance(evaluation, Eval):
        raise TypeError(f"Expected Eval. Observed: {type(evaluation).__name__}")
    existing = _REGISTRY.get(evaluation.name)
    if existing is not None and existing is not evaluation:
        raise ValueError(f"eval {evaluation.name!r} is already registered")
    _REGISTRY[evaluation.name] = evaluation
    return evaluation


def get_eval(name: str) -> Eval:
    """Return a registered eval by name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(registered_evals()) or "(none)"
        raise KeyError(f"Unknown eval {name!r}. Registered: {known}") from None


def registered_evals() -> tuple[str, ...]:
    """Names of evals registered with ``@eval_case`` or ``register_eval``."""
    return tuple(sorted(_REGISTRY))


def eval_case(
    func: Callable[[AgentExecutionResult], Score | float | bool] | None = None,
    *,
    name: str | None = None,
    threshold: float = 1.0,
    register: bool = True,
) -> Any:
    """Register a function as an eval.

    The function receives an ``AgentExecutionResult`` and returns a score in
    ``[0.0, 1.0]``, a bool, or a ``Score``. The eval passes when the score is
    at least ``threshold``.
    """

    def decorate(fn: Callable[[AgentExecutionResult], Score | float | bool]) -> Eval:
        label = name or fn.__name__

        class _FunctionEval(Eval):
            def score(self, result: AgentExecutionResult) -> Score | float | bool:
                return fn(result)

        _FunctionEval.__name__ = label
        _FunctionEval.__doc__ = fn.__doc__
        evaluation = _FunctionEval(name=label, threshold=threshold)
        if register:
            register_eval(evaluation)
        return evaluation

    if func is not None:
        return decorate(func)
    return decorate


def _as_evals(evals: Eval | Sequence[Eval]) -> tuple[Eval, ...]:
    selected = (evals,) if isinstance(evals, Eval) else tuple(evals)
    if not selected:
        raise ValueError("at least one eval is required")
    for item in selected:
        if not isinstance(item, Eval):
            raise TypeError(f"Expected Eval. Observed: {type(item).__name__}")
    return selected


def _coerce_score(name: str, raw: object) -> tuple[float, str | None, dict[str, Any]]:
    if isinstance(raw, Score):
        return raw.value, raw.reason, dict(raw.details)
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0), None, {}
    if isinstance(raw, int | float):
        validate_unit_interval(f"eval {name} score", raw)
        return float(raw), None, {}
    raise TypeError(
        f"Eval {name!r} must return a Score, float, or bool. Observed: {type(raw).__name__}"
    )
