"""Workflow and tool-call assertion engine."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.tool_call import ToolCall

ToolIdentifier: TypeAlias = tuple[str | None, str]
ArgumentPredicate: TypeAlias = Callable[[Mapping[str, Any]], bool]
StatusFilter: TypeAlias = ToolCallStatus | set[ToolCallStatus] | frozenset[ToolCallStatus] | None


def _normalize_step(step: ToolIdentifier) -> ToolIdentifier:
    server, name = step
    return (server, name)


def _format_step(step: ToolIdentifier) -> str:
    server, name = step
    if server:
        return f"{server}/{name}"
    return name


def _is_subset(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping) or not _is_subset(
                expected_value, actual_value
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _status_matches(call: ToolCall, status: StatusFilter) -> bool:
    if status is None:
        return True
    if isinstance(status, ToolCallStatus):
        return call.status == status
    return call.status in status


def validate_call_count_constraints(
    exact: int | None,
    min_calls: int | None,
    max_calls: int | None,
) -> None:
    """Validate a call-count range before evaluating any calls."""
    if exact is not None and min_calls is not None:
        raise ValueError("exact is mutually exclusive with min_calls")
    if exact is not None and max_calls is not None:
        raise ValueError("exact is mutually exclusive with max_calls")
    if min_calls is not None and max_calls is not None and min_calls > max_calls:
        raise ValueError("min_calls cannot exceed max_calls")


@dataclass(frozen=True, slots=True)
class ToolStep:
    """A single expected workflow step."""

    server: str | None
    name: str
    status: ToolCallStatus | None = None
    arguments: Mapping[str, Any] | None = None
    argument_predicate: ArgumentPredicate | None = None

    @property
    def qualified_name(self) -> ToolIdentifier:
        return (self.server, self.name)

    def matches(self, call: ToolCall, *, default_status: StatusFilter = None) -> bool:
        status: StatusFilter = self.status if self.status is not None else default_status
        if call.qualified_name != self.qualified_name or not _status_matches(call, status):
            return False
        if self.arguments is not None and not _is_subset(self.arguments, call.arguments):
            return False
        return self.argument_predicate is None or self.argument_predicate(call.arguments)


@dataclass(frozen=True, slots=True)
class OptionalStep:
    """An expected workflow step that may be absent."""

    step: ToolStep


@dataclass(frozen=True, slots=True, init=False)
class AnyOfStep:
    """One of several alternative workflow steps."""

    steps: tuple[ToolStep, ...]

    def __init__(self, *steps: ToolStep) -> None:
        if not steps:
            raise ValueError("AnyOfStep requires at least one alternative")
        object.__setattr__(self, "steps", steps)


WorkflowStep: TypeAlias = ToolIdentifier | ToolStep | OptionalStep | AnyOfStep


def _as_tool_step(step: ToolIdentifier | ToolStep) -> ToolStep:
    if isinstance(step, ToolStep):
        return step
    server, name = _normalize_step(step)
    return ToolStep(server, name)


def _step_matches(step: WorkflowStep, call: ToolCall, status: StatusFilter) -> bool:
    if isinstance(step, OptionalStep):
        return step.step.matches(call, default_status=status)
    if isinstance(step, AnyOfStep):
        return any(alternative.matches(call, default_status=status) for alternative in step.steps)
    return _as_tool_step(step).matches(call, default_status=status)


def _step_label(step: WorkflowStep) -> str:
    if isinstance(step, OptionalStep):
        return f"optional({_format_step(step.step.qualified_name)})"
    if isinstance(step, AnyOfStep):
        choices = ", ".join(_format_step(choice.qualified_name) for choice in step.steps)
        return f"any_of({choices})"
    return _format_step(_as_tool_step(step).qualified_name)


class FlowAssertionEngine:
    """Evaluates tool-call workflow assertions against an execution result."""

    def __init__(self, result: AgentExecutionResult) -> None:
        self._result = result
        self._calls = result.tool_calls

    def matching_calls(
        self,
        tool_name: str,
        *,
        server: str | None = None,
        status: StatusFilter = None,
        arguments: Mapping[str, Any] | None = None,
        argument_predicate: ArgumentPredicate | None = None,
    ) -> list[ToolCall]:
        return [
            call
            for call in self._calls
            if call.matches(tool_name, server)
            and _status_matches(call, status)
            and (arguments is None or _is_subset(arguments, call.arguments))
            and (argument_predicate is None or argument_predicate(call.arguments))
        ]

    def assert_tool_called(
        self,
        tool_name: str,
        server: str | None = None,
        *,
        status: StatusFilter = None,
        arguments: Mapping[str, Any] | None = None,
        argument_predicate: ArgumentPredicate | None = None,
    ) -> None:
        matches = self.matching_calls(
            tool_name,
            server=server,
            status=status,
            arguments=arguments,
            argument_predicate=argument_predicate,
        )
        if not matches:
            label = _format_step((server, tool_name))
            observed = [
                {
                    "tool": _format_step(call.qualified_name),
                    "status": call.status.value,
                    "arguments": call.arguments,
                }
                for call in self._calls
                if call.matches(tool_name, server)
            ]
            expectation = f"Expected tool {label!r} to be called"
            if status is not None:
                expectation += f" with status {status!r}"
            if arguments is not None:
                expectation += f". Expected arguments subset: {dict(arguments)!r}"
            if argument_predicate is not None:
                expectation += ". Expected argument predicate to pass"
            raise AssertionError(f"{expectation}. Observed matching calls: {observed}")

    def assert_tool_not_called(self, tool_name: str, server: str | None = None) -> None:
        matches = self.matching_calls(tool_name, server=server)
        if matches:
            label = _format_step((server, tool_name))
            raise AssertionError(f"Expected tool {label!r} not to be called, but it was.")

    def assert_tool_order(
        self,
        *,
        before: ToolIdentifier,
        after: ToolIdentifier,
        status: StatusFilter = None,
        before_status: StatusFilter = None,
        after_status: StatusFilter = None,
    ) -> None:
        before_step = _normalize_step(before)
        after_step = _normalize_step(after)
        effective_before_status = before_status if before_status is not None else status
        effective_after_status = after_status if after_status is not None else status
        before_indexes = [
            index
            for index, call in enumerate(self._calls)
            if call.qualified_name == before_step and _status_matches(call, effective_before_status)
        ]
        after_indexes = [
            index
            for index, call in enumerate(self._calls)
            if call.qualified_name == after_step and _status_matches(call, effective_after_status)
        ]
        if not before_indexes:
            raise AssertionError(f"Tool {_format_step(before_step)!r} was not called")
        if not after_indexes:
            raise AssertionError(f"Tool {_format_step(after_step)!r} was not called")
        if min(before_indexes) >= min(after_indexes):
            raise AssertionError(
                f"Expected {_format_step(before_step)!r} before "
                f"{_format_step(after_step)!r}, but order was reversed"
            )

    def assert_tool_sequence(
        self,
        sequence: Sequence[WorkflowStep],
        *,
        allow_additional_read_tools: bool = False,
        status: StatusFilter = None,
    ) -> None:
        calls = [call for call in self._calls if _status_matches(call, status)]
        if allow_additional_read_tools:
            unexpected_non_read_calls = [
                call
                for call in self._calls
                if not call.is_read
                and not any(_step_matches(step, call, status) for step in sequence)
            ]
            if unexpected_non_read_calls:
                call = unexpected_non_read_calls[0]
                raise AssertionError(
                    f"Unexpected non-read tool {_format_step(call.qualified_name)!r} "
                    "while matching sequence"
                )
        observed_index = 0
        for step in sequence:
            if isinstance(step, OptionalStep):
                optional_index = observed_index
                while optional_index < len(calls):
                    call = calls[optional_index]
                    if _step_matches(step, call, status):
                        observed_index = optional_index + 1
                        break
                    if not allow_additional_read_tools or not call.is_read:
                        break
                    optional_index += 1
                continue

            found = False
            while observed_index < len(calls):
                call = calls[observed_index]
                if _step_matches(step, call, status):
                    observed_index += 1
                    found = True
                    break
                if not allow_additional_read_tools:
                    break
                if not call.is_read:
                    raise AssertionError(
                        f"Unexpected non-read tool {_format_step(call.qualified_name)!r} "
                        f"while matching sequence near {_step_label(step)!r}"
                    )
                observed_index += 1
            if not found:
                observed = [
                    f"{_format_step(call.qualified_name)}[{call.status.value}]" for call in calls
                ]
                raise AssertionError(
                    f"Expected step {_step_label(step)!r} in sequence. Observed: {observed}"
                )

        remaining = calls[observed_index:]
        if allow_additional_read_tools:
            unsafe = [call for call in remaining if not call.is_read]
            if unsafe:
                call = unsafe[0]
                raise AssertionError(
                    f"Unexpected non-read tool {_format_step(call.qualified_name)!r} "
                    "after expected sequence"
                )
        elif remaining:
            expected = [_step_label(step) for step in sequence]
            observed = [
                f"{_format_step(call.qualified_name)}[{call.status.value}]" for call in calls
            ]
            raise AssertionError(
                f"Tool sequence mismatch.\nExpected: {expected}\nObserved: {observed}"
            )

    def assert_read_before_write(
        self,
        *,
        read_tool: tuple[str | None, str],
        write_tool: tuple[str | None, str],
    ) -> None:
        self.assert_tool_order(before=read_tool, after=write_tool)

    def assert_tool_call_count(
        self,
        tool_name: str,
        *,
        server: str | None = None,
        exact: int | None = None,
        min_calls: int | None = None,
        max_calls: int | None = None,
        status: StatusFilter = None,
        arguments: Mapping[str, Any] | None = None,
        argument_predicate: ArgumentPredicate | None = None,
    ) -> None:
        bounds = [value for value in (exact, min_calls, max_calls) if value is not None]
        if not bounds:
            raise ValueError("Provide exact, min_calls, or max_calls")
        if any(value < 0 for value in bounds):
            raise ValueError("Call count bounds must be non-negative")
        validate_call_count_constraints(exact, min_calls, max_calls)
        lower = exact if exact is not None else min_calls
        upper = exact if exact is not None else max_calls

        actual = len(
            self.matching_calls(
                tool_name,
                server=server,
                status=status,
                arguments=arguments,
                argument_predicate=argument_predicate,
            )
        )
        if (lower is not None and actual < lower) or (upper is not None and actual > upper):
            if exact is not None:
                expected = f"exactly {exact}"
            elif lower is not None and upper is not None:
                expected = f"between {lower} and {upper}"
            elif lower is not None:
                expected = f"at least {lower}"
            else:
                expected = f"at most {upper}"
            label = _format_step((server, tool_name))
            raise AssertionError(
                f"Expected {label!r} call count to be {expected}. Observed: {actual}"
            )

    def assert_max_workflow_steps(self, maximum: int) -> None:
        if maximum < 0:
            raise ValueError("Maximum workflow steps must be non-negative")
        actual = len(self._calls)
        if actual > maximum:
            raise AssertionError(f"Expected at most {maximum} workflow steps. Observed: {actual}")

    def assert_max_tool_attempts(
        self,
        maximum: int,
        *,
        tool_name: str | None = None,
        server: str | None = None,
    ) -> None:
        if maximum < 1:
            raise ValueError("Maximum attempts must be at least one")
        calls = self._calls if tool_name is None else self.matching_calls(tool_name, server=server)
        offenders = [call for call in calls if call.attempt > maximum]
        if offenders:
            observed = {_format_step(call.qualified_name): call.attempt for call in offenders}
            raise AssertionError(
                f"Expected at most {maximum} attempts per tool call. Observed: {observed}"
            )

    def assert_max_retries(
        self,
        maximum: int,
        *,
        tool_name: str | None = None,
        server: str | None = None,
    ) -> None:
        if maximum < 0:
            raise ValueError("Maximum retries must be non-negative")
        self.assert_max_tool_attempts(
            maximum + 1,
            tool_name=tool_name,
            server=server,
        )

    def assert_no_failed_tool_calls(
        self,
        tool_name: str | None = None,
        *,
        server: str | None = None,
    ) -> None:
        failed_statuses = {ToolCallStatus.ERROR, ToolCallStatus.TIMEOUT}
        failed = [
            call
            for call in self._calls
            if call.status in failed_statuses
            and (tool_name is None or call.matches(tool_name, server))
        ]
        if failed:
            observed = [
                f"{_format_step(call.qualified_name)}[{call.status.value}]" for call in failed
            ]
            raise AssertionError(f"Expected no failed tool calls. Observed: {observed}")

    def assert_read_only(self) -> None:
        unsafe = [call for call in self._calls if not call.is_read]
        if unsafe:
            observed = [
                f"{_format_step(call.qualified_name)}[{call.operation_kind.value}]"
                for call in unsafe
            ]
            raise AssertionError(
                "Expected a read-only workflow; UNKNOWN and WRITE operations are unsafe. "
                f"Observed unsafe calls: {observed}"
            )

    def assert_no_duplicate_tool_writes(self) -> None:
        write_keys = [
            call.qualified_name
            for call in self._calls
            if call.is_write or call.operation_kind == ToolOperationKind.WRITE
        ]
        duplicates = [key for key, count in Counter(write_keys).items() if count > 1]
        if duplicates:
            formatted = [_format_step(key) for key in duplicates]
            raise AssertionError(f"Duplicate write tools detected: {formatted}")

    def assert_write_tool_called_once(
        self,
        *,
        server: str | None,
        tool: str,
    ) -> None:
        matches = self.matching_calls(tool, server=server)
        write_matches = [
            call
            for call in matches
            if call.is_write or call.operation_kind == ToolOperationKind.WRITE
        ]
        if len(write_matches) != 1:
            label = _format_step((server, tool))
            raise AssertionError(
                f"Expected exactly one write call to {label!r}, found {len(write_matches)}"
            )
