"""Guardrails that share one definition across recorded traces and live runs."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace
from agent_test_kit.scoring import response_text

GuardrailPhase = Literal["message", "tool_call", "trace"]
GuardrailMode = Literal["offline", "online"]


@dataclass(frozen=True, slots=True)
class GuardrailViolation:
    """One guardrail failure."""

    guardrail: str
    message: str
    phase: GuardrailPhase = "trace"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuardrailCheck:
    """Outcome of one guardrail against a trace or a live session."""

    name: str
    passed: bool
    mode: GuardrailMode
    message: str | None = None
    violations: tuple[GuardrailViolation, ...] = ()

    def assert_passed(self) -> None:
        if not self.passed:
            raise AssertionError(f"Guardrail {self.name!r} failed: {self.message}")


@dataclass(frozen=True, slots=True)
class GuardrailReport:
    """Aggregate of every guardrail checked together."""

    checks: tuple[GuardrailCheck, ...]
    mode: GuardrailMode

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def violations(self) -> tuple[GuardrailViolation, ...]:
        return tuple(violation for check in self.checks for violation in check.violations)

    def assert_passed(self) -> None:
        if self.passed:
            return
        lines = [f"{check.name}: {check.message}" for check in self.checks if not check.passed]
        raise AssertionError("Guardrail violations:\n" + "\n".join(lines))


@dataclass(frozen=True, slots=True)
class GuardrailEvent:
    """One streamed message or tool call seen by an online guardrail."""

    type: Literal["message", "tool_call"]
    text: str | None = None
    role: str = "assistant"
    tool_call: ToolCall | None = None


class GuardrailViolationError(AssertionError):
    """Raised when an online guardrail is configured to fail on the first violation."""

    def __init__(self, violation: GuardrailViolation) -> None:
        self.violation = violation
        super().__init__(f"Guardrail {violation.guardrail!r} failed: {violation.message}")


class Guardrail:
    """Base class for a guardrail that works offline and online.

    Override the hooks you need. ``check`` replays a recorded result through
    those hooks. ``GuardrailMonitor`` calls the same hooks as events arrive.
    Return a violation message from a hook, or ``None`` when the event is allowed.
    """

    name: str = "guardrail"

    def on_message(self, text: str, *, role: str = "assistant") -> str | None:
        """Inspect one message. Assistant output is the usual place to look."""
        return None

    def on_tool_call(self, call: ToolCall) -> str | None:
        """Inspect one tool call as it happens."""
        return None

    def on_trace(self, result: AgentExecutionResult) -> str | None:
        """Inspect the finished run. Online monitors call this from ``finish``."""
        return None

    def check(self, result: AgentExecutionResult) -> GuardrailCheck:
        """Run this guardrail against a recorded result."""
        violations: list[GuardrailViolation] = []
        text = response_text(result)
        if text.strip():
            found = self._message_violation(text, role="assistant")
            if found is not None:
                violations.append(found)
        for call in result.tool_calls:
            found = self._tool_violation(call)
            if found is not None:
                violations.append(found)
        found = self._trace_violation(result)
        if found is not None:
            violations.append(found)
        return _check_from_violations(self.name, violations, mode="offline")

    def __call__(self, result: AgentExecutionResult) -> GuardrailCheck:
        return self.check(result)

    def _message_violation(self, text: str, *, role: str) -> GuardrailViolation | None:
        message = _coerce_violation(self.name, self.on_message(text, role=role))
        if message is None:
            return None
        return GuardrailViolation(
            guardrail=self.name,
            message=message,
            phase="message",
            evidence={"role": role},
        )

    def _tool_violation(self, call: ToolCall) -> GuardrailViolation | None:
        message = _coerce_violation(self.name, self.on_tool_call(call))
        if message is None:
            return None
        return GuardrailViolation(
            guardrail=self.name,
            message=message,
            phase="tool_call",
            evidence={"server": call.server, "tool": call.name},
        )

    def _trace_violation(self, result: AgentExecutionResult) -> GuardrailViolation | None:
        message = _coerce_violation(self.name, self.on_trace(result))
        if message is None:
            return None
        return GuardrailViolation(guardrail=self.name, message=message, phase="trace")


def check_guardrails(
    result: AgentExecutionResult,
    guardrails: Guardrail | Sequence[Guardrail],
) -> GuardrailReport:
    """Run guardrails offline against a recorded execution result."""
    selected = _as_guardrails(guardrails)
    checks = tuple(item.check(result) for item in selected)
    return GuardrailReport(checks=checks, mode="offline")


class GuardrailMonitor:
    """Online middleware. Feed messages and tool calls as the agent produces them.

    Message and tool-call hooks run immediately. Trace hooks, including a required
    final tool, run when ``finish`` is called. ``fail_fast=True`` raises
    ``GuardrailViolationError`` at the first violation so the caller can stop the run.
    """

    def __init__(
        self,
        guardrails: Guardrail | Sequence[Guardrail],
        *,
        fail_fast: bool = False,
        on_finish: Callable[[GuardrailReport], None] | None = None,
    ) -> None:
        self.guardrails = _as_guardrails(guardrails)
        self.fail_fast = fail_fast
        self._on_finish = on_finish
        self._violations: list[list[GuardrailViolation]] = [[] for _ in self.guardrails]
        self._messages: list[tuple[str, str]] = []
        self._calls: list[ToolCall] = []
        self._finished = False
        self.last_report: GuardrailReport | None = None

    @property
    def finished(self) -> bool:
        return self._finished

    def on_message(self, text: str, *, role: str = "assistant") -> list[GuardrailViolation]:
        """Record one streamed message and run message hooks."""
        self._ensure_open()
        if not isinstance(text, str):
            raise TypeError("message text must be a string")
        self._messages.append((role, text))
        found = self._run_message_hooks(text, role=role)
        self._raise_fast(found)
        return found

    def on_tool_call(self, call: ToolCall | Mapping[str, Any]) -> list[GuardrailViolation]:
        """Record one tool call and run tool-call hooks."""
        self._ensure_open()
        tool_call = call if isinstance(call, ToolCall) else ToolCall.model_validate(dict(call))
        self._calls.append(tool_call)
        found = self._run_tool_hooks(tool_call)
        self._raise_fast(found)
        return found

    def handle(self, event: GuardrailEvent | Mapping[str, Any]) -> list[GuardrailViolation]:
        """Middleware entry point for one streamed event.

        Message events use ``type="message"`` and ``text`` (or ``content``).
        Tool events use ``type="tool_call"`` plus ``name`` or a nested ``tool_call``.
        """
        parsed = event if isinstance(event, GuardrailEvent) else _parse_event(event)
        if parsed.type == "message":
            return self.on_message(parsed.text or "", role=parsed.role)
        if parsed.tool_call is None:
            raise ValueError("tool_call event requires a tool call")
        return self.on_tool_call(parsed.tool_call)

    def finish(
        self,
        result: AgentExecutionResult | None = None,
        *,
        notify: bool = True,
        raise_on_violation: bool | None = None,
    ) -> GuardrailReport:
        """Finish the live run and evaluate trace-level guardrails.

        When ``result`` is omitted, the trace is the messages and tool calls already
        observed. ``raise_on_violation`` defaults to ``fail_fast``.
        """
        if self._finished:
            raise RuntimeError("GuardrailMonitor.finish() was already called")
        should_raise = self.fail_fast if raise_on_violation is None else raise_on_violation
        self._replay(result)
        self._scan_joined_messages()
        trace = result if result is not None else self._synthetic_result()
        self._run_trace_hooks(trace)
        self._finished = True
        report = self._build_report()
        self.last_report = report
        if result is not None:
            result.guardrail_checks.extend(report.checks)
        if should_raise and not report.passed:
            raise GuardrailViolationError(report.violations[0])
        if notify and self._on_finish is not None:
            self._on_finish(report)
        return report

    def _ensure_open(self) -> None:
        if self._finished:
            raise RuntimeError("GuardrailMonitor is already finished")

    def _raise_fast(self, found: list[GuardrailViolation]) -> None:
        if self.fail_fast and found:
            self.last_report = self._build_report()
            raise GuardrailViolationError(found[0])

    def _scan_joined_messages(self) -> None:
        """Catch a disallowed word that was split across streamed chunks."""
        assistant = [message for role, message in self._messages if role == "assistant"]
        joined = "".join(assistant)
        if joined.strip() and joined not in assistant:
            self._run_message_hooks(joined, role="assistant")

    def _replay(self, result: AgentExecutionResult | None) -> None:
        if result is None:
            return
        text = response_text(result)
        observed = [message for role, message in self._messages if role == "assistant"]
        if text.strip() and text not in observed and "".join(observed) != text:
            self._messages.append(("assistant", text))
            self._run_message_hooks(text, role="assistant")
        if not self._calls:
            for call in result.tool_calls:
                self._calls.append(call)
                self._run_tool_hooks(call)

    def _run_message_hooks(self, text: str, *, role: str) -> list[GuardrailViolation]:
        found: list[GuardrailViolation] = []
        for index, guard in enumerate(self.guardrails):
            violation = guard._message_violation(text, role=role)
            if violation is not None:
                self._violations[index].append(violation)
                found.append(violation)
        return found

    def _run_tool_hooks(self, call: ToolCall) -> list[GuardrailViolation]:
        found: list[GuardrailViolation] = []
        for index, guard in enumerate(self.guardrails):
            violation = guard._tool_violation(call)
            if violation is not None:
                self._violations[index].append(violation)
                found.append(violation)
        return found

    def _run_trace_hooks(self, result: AgentExecutionResult) -> None:
        for index, guard in enumerate(self.guardrails):
            violation = guard._trace_violation(result)
            if violation is not None:
                self._violations[index].append(violation)

    def _synthetic_result(self) -> AgentExecutionResult:
        text = "".join(message for role, message in self._messages if role == "assistant")
        return AgentExecutionResult(
            success=True,
            run_id="online",
            response=text or None,
            trace=AgentTrace(tool_calls=list(self._calls)),
        )

    def _build_report(self) -> GuardrailReport:
        checks = tuple(
            _check_from_violations(guard.name, self._violations[index], mode="online")
            for index, guard in enumerate(self.guardrails)
        )
        return GuardrailReport(checks=checks, mode="online")


def guardrail(
    func: Callable[..., str | None] | None = None,
    *,
    name: str | None = None,
    phase: GuardrailPhase = "trace",
) -> Any:
    """Turn a function into a guardrail.

    ``phase="message"`` receives ``(text, *, role)``. ``role`` is omitted when the
    function does not accept it. ``phase="tool_call"`` receives a ``ToolCall``.
    ``phase="trace"`` receives an ``AgentExecutionResult``. Return a violation
    message, or ``None`` when the event is allowed.
    """
    if phase not in {"message", "tool_call", "trace"}:
        raise ValueError("phase must be 'message', 'tool_call', or 'trace'")

    def decorate(fn: Callable[..., str | None]) -> Guardrail:
        label = _require_name(name or fn.__name__, what="guardrail name")

        class _FunctionGuardrail(Guardrail):
            pass

        _FunctionGuardrail.name = label
        _FunctionGuardrail.__name__ = label
        _FunctionGuardrail.__doc__ = fn.__doc__
        if phase == "message":
            accepts_role = _accepts_keyword(fn, "role")

            def on_message(
                self: Guardrail,
                text: str,
                *,
                role: str = "assistant",
            ) -> str | None:
                if accepts_role:
                    return fn(text, role=role)
                return fn(text)

            _FunctionGuardrail.on_message = on_message  # type: ignore[method-assign]
        elif phase == "tool_call":

            def on_tool_call(self: Guardrail, call: ToolCall) -> str | None:
                return fn(call)

            _FunctionGuardrail.on_tool_call = on_tool_call  # type: ignore[method-assign]
        else:

            def on_trace(self: Guardrail, result: AgentExecutionResult) -> str | None:
                return fn(result)

            _FunctionGuardrail.on_trace = on_trace  # type: ignore[method-assign]
        return _FunctionGuardrail()

    if func is not None:
        return decorate(func)
    return decorate


def _as_guardrails(guardrails: Guardrail | Sequence[Guardrail]) -> tuple[Guardrail, ...]:
    selected = (guardrails,) if isinstance(guardrails, Guardrail) else tuple(guardrails)
    if not selected:
        raise ValueError("at least one guardrail is required")
    for item in selected:
        if not isinstance(item, Guardrail):
            raise TypeError(f"Expected Guardrail. Observed: {type(item).__name__}")
    return selected


def _coerce_violation(name: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise TypeError(
        f"Guardrail {name!r} must return a violation message or None. "
        f"Observed: {type(value).__name__}"
    )


def _check_from_violations(
    name: str,
    violations: Sequence[GuardrailViolation],
    *,
    mode: GuardrailMode,
) -> GuardrailCheck:
    unique = _dedupe_violations(violations)
    if not unique:
        return GuardrailCheck(name=name, passed=True, mode=mode)
    message = "; ".join(item.message for item in unique)
    return GuardrailCheck(
        name=name,
        passed=False,
        mode=mode,
        message=message,
        violations=unique,
    )


def _dedupe_violations(
    violations: Sequence[GuardrailViolation],
) -> tuple[GuardrailViolation, ...]:
    unique: list[GuardrailViolation] = []
    seen: set[tuple[str, str, str]] = set()
    for violation in violations:
        key = (violation.guardrail, violation.phase, violation.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(violation)
    return tuple(unique)


def _require_name(name: str, *, what: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return name


def _accepts_keyword(func: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == keyword:
            return True
    return False


def _parse_event(event: Mapping[str, Any]) -> GuardrailEvent:
    if isinstance(event, str) or not isinstance(event, Mapping):
        raise TypeError("guardrail event must be a mapping or GuardrailEvent")
    event_type = event.get("type")
    if event_type == "message":
        text = event.get("text", event.get("content", ""))
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise TypeError("message text must be a string")
        role = event.get("role") or "assistant"
        if not isinstance(role, str):
            raise TypeError("message role must be a string")
        return GuardrailEvent(type="message", text=text, role=role)
    if event_type == "tool_call":
        return GuardrailEvent(type="tool_call", tool_call=_tool_call_from_event(event))
    raise ValueError(f"Unknown guardrail event type: {event_type!r}")


def _tool_call_from_event(payload: Mapping[str, Any]) -> ToolCall:
    nested = payload.get("tool_call", payload.get("tool"))
    if isinstance(nested, ToolCall):
        return nested
    if isinstance(nested, Mapping):
        return ToolCall.model_validate(dict(nested))
    data = {
        key: payload[key]
        for key in ("name", "server", "arguments", "status", "operation_kind", "output", "id")
        if key in payload
    }
    if "name" not in data:
        raise ValueError("tool_call event requires a name")
    return ToolCall.model_validate(data)
