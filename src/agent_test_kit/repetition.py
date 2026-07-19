"""Deterministic repeated execution and idempotency assertions."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Hashable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.run_context import RunContext
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

ContextFactory = Callable[[int, str], RunContext]
AsyncExecutionCallable = Callable[
    [dict[str, Any], RunContext],
    Awaitable[AgentExecutionResult],
]
ResponseComparator = Callable[[Any, Any], bool]
TraceComparator = Callable[[AgentTrace, AgentTrace], bool]
WriteIdentity = Callable[[ToolCall], Hashable]


@runtime_checkable
class AsyncAgentExecutor(Protocol):
    """Executor contract implemented by agent clients."""

    async def execute(
        self,
        input: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        """Execute one agent run."""


@dataclass(frozen=True, slots=True)
class RepeatedExecutionResult:
    """Typed aggregate returned by repeated agent execution."""

    results: tuple[AgentExecutionResult, ...]
    contexts: tuple[RunContext, ...]
    idempotency_key: str

    def assert_stable_success(self) -> None:
        failures = [
            {
                "run": index,
                "run_id": result.run_id,
                "error": result.error,
            }
            for index, result in enumerate(self.results, start=1)
            if not result.success
        ]
        if failures:
            raise AssertionError(
                f"Expected every repeated execution to succeed. Observed failures: {failures}"
            )

    def assert_no_duplicate_writes(
        self,
        *,
        identity: WriteIdentity | None = None,
    ) -> None:
        identify = identity or _default_write_identity
        seen: dict[Hashable, int] = {}
        duplicates: list[str] = []
        for run_index, result in enumerate(self.results, start=1):
            for call in result.tool_calls:
                if not call.is_write:
                    continue
                key = identify(call)
                if key in seen:
                    label = _format_call(call)
                    duplicates.append(
                        f"{label} (runs {seen[key]} and {run_index}, arguments={call.arguments!r})"
                    )
                else:
                    seen[key] = run_index
        if duplicates:
            raise AssertionError(f"Duplicate writes across runs were detected: {duplicates}")

    def assert_responses_stable(
        self,
        *,
        comparator: ResponseComparator | None = None,
    ) -> None:
        compare = comparator or _equal
        self._assert_stable_values(
            [result.response for result in self.results],
            compare,
            label="responses",
        )

    def assert_traces_stable(
        self,
        *,
        comparator: TraceComparator | None = None,
    ) -> None:
        compare = comparator or _traces_equal
        self._assert_stable_values(
            [result.trace for result in self.results],
            compare,
            label="traces",
        )

    @staticmethod
    def _assert_stable_values(
        values: list[Any],
        comparator: Callable[[Any, Any], bool],
        *,
        label: str,
    ) -> None:
        if not values:
            return
        baseline = values[0]
        for index, current in enumerate(values[1:], start=2):
            if not comparator(baseline, current):
                raise AssertionError(
                    f"Expected repeated execution {label} to remain stable. "
                    f"Baseline: {baseline!r}. Observed run {index}: {current!r}"
                )


async def run_repeatedly(
    executor: AsyncAgentExecutor | AsyncExecutionCallable,
    *,
    input: Mapping[str, Any],
    runs: int,
    idempotency_key: str,
    context_factory: ContextFactory | None = None,
) -> RepeatedExecutionResult:
    """Invoke an async executor repeatedly with one stable idempotency key."""
    if runs < 1:
        raise ValueError("runs must be at least one")
    if not idempotency_key:
        raise ValueError("idempotency_key must not be empty")

    factory = context_factory or _default_context_factory
    contexts: list[RunContext] = []
    results: list[AgentExecutionResult] = []
    for index in range(runs):
        context = factory(index, idempotency_key)
        context.idempotency_key = idempotency_key
        contexts.append(context)
        payload = dict(input)
        if isinstance(executor, AsyncAgentExecutor):
            result = await executor.execute(payload, run_context=context)
        else:
            result = await executor(payload, context)
        results.append(result)

    return RepeatedExecutionResult(
        results=tuple(results),
        contexts=tuple(contexts),
        idempotency_key=idempotency_key,
    )


def _default_context_factory(_index: int, idempotency_key: str) -> RunContext:
    return RunContext(idempotency_key=idempotency_key)


def _default_write_identity(call: ToolCall) -> Hashable:
    arguments = json.dumps(
        call.arguments,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
    return (call.server, call.name, arguments)


def _format_call(call: ToolCall) -> str:
    return f"{call.server}/{call.name}" if call.server else call.name


def _equal(first: Any, current: Any) -> bool:
    return bool(first == current)


def _traces_equal(first: AgentTrace, current: AgentTrace) -> bool:
    return first.model_dump(mode="json") == current.model_dump(mode="json")
