"""Workflow and tool-call assertion engine."""

from __future__ import annotations

from collections import Counter

from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.tool_call import ToolCall


def _normalize_step(step: tuple[str | None, str]) -> tuple[str | None, str]:
    server, name = step
    return (server, name)


def _format_step(step: tuple[str | None, str]) -> str:
    server, name = step
    if server:
        return f"{server}/{name}"
    return name


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
    ) -> list[ToolCall]:
        return [call for call in self._calls if call.matches(tool_name, server)]

    def assert_tool_called(self, tool_name: str, server: str | None = None) -> None:
        matches = self.matching_calls(tool_name, server=server)
        if not matches:
            label = _format_step((server, tool_name))
            observed = [_format_step(call.qualified_name) for call in self._calls]
            raise AssertionError(
                f"Expected tool {label!r} to be called. Observed tools: {observed}"
            )

    def assert_tool_not_called(self, tool_name: str, server: str | None = None) -> None:
        matches = self.matching_calls(tool_name, server=server)
        if matches:
            label = _format_step((server, tool_name))
            raise AssertionError(f"Expected tool {label!r} not to be called, but it was.")

    def assert_tool_order(
        self,
        *,
        before: tuple[str | None, str],
        after: tuple[str | None, str],
    ) -> None:
        before_step = _normalize_step(before)
        after_step = _normalize_step(after)
        before_indexes = [
            index for index, call in enumerate(self._calls) if call.qualified_name == before_step
        ]
        after_indexes = [
            index for index, call in enumerate(self._calls) if call.qualified_name == after_step
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
        sequence: list[tuple[str | None, str]],
        *,
        allow_additional_read_tools: bool = False,
    ) -> None:
        expected = [_normalize_step(step) for step in sequence]
        observed = [call.qualified_name for call in self._calls]

        if not allow_additional_read_tools:
            if observed != expected:
                raise AssertionError(
                    f"Tool sequence mismatch.\nExpected: {expected}\nObserved: {observed}"
                )
            return

        observed_index = 0
        for step in expected:
            found = False
            while observed_index < len(self._calls):
                call = self._calls[observed_index]
                observed_index += 1
                if call.qualified_name == step:
                    found = True
                    break
                if call.operation_kind != ToolOperationKind.READ:
                    raise AssertionError(
                        f"Unexpected non-read tool {_format_step(call.qualified_name)!r} "
                        f"while matching sequence near {_format_step(step)!r}"
                    )
            if not found:
                raise AssertionError(
                    f"Expected tool {_format_step(step)!r} in sequence. "
                    f"Observed: {[_format_step(name) for name in observed]}"
                )

    def assert_read_before_write(
        self,
        *,
        read_tool: tuple[str | None, str],
        write_tool: tuple[str | None, str],
    ) -> None:
        self.assert_tool_order(before=read_tool, after=write_tool)

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
