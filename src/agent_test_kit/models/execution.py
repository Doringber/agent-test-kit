"""Agent execution result models with workflow assertions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent_test_kit.models.run_context import RunContext
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

if TYPE_CHECKING:
    from agent_test_kit.assertions.flow import (
        FlowAssertionEngine,
        StatusFilter,
        WorkflowStep,
    )
    from agent_test_kit.models.enums import ToolCallStatus
    from agent_test_kit.scoring import Score, Scorer


class AssertionOutcome(BaseModel):
    """Structured result captured for an execution assertion."""

    name: str
    passed: bool
    expected: Any | None = None
    actual: Any | None = None
    message: str | None = None


class AgentExecutionResult(BaseModel):
    """Result of a single agent execution, including trace and assertions."""

    success: bool
    run_id: str
    trace_id: str | None = None
    correlation_id: str | None = None
    response: Any | None = None
    error: str | None = None
    trace: AgentTrace = Field(default_factory=AgentTrace)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    assertions: list[str] = Field(default_factory=list)
    assertion_outcomes: list[AssertionOutcome] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.trace.tool_calls

    def _engine(self) -> FlowAssertionEngine:
        from agent_test_kit.assertions.flow import FlowAssertionEngine

        return FlowAssertionEngine(self)

    def _capture_assertion(
        self,
        name: str,
        *,
        expected: Any,
        actual: Any,
        assertion: Callable[[], None],
    ) -> None:
        try:
            assertion()
        except AssertionError as exc:
            self.assertion_outcomes.append(
                AssertionOutcome(
                    name=name,
                    passed=False,
                    expected=expected,
                    actual=actual,
                    message=str(exc),
                )
            )
            raise
        self.assertion_outcomes.append(
            AssertionOutcome(
                name=name,
                passed=True,
                expected=expected,
                actual=actual,
            )
        )

    def assert_success(self) -> None:
        def evaluate() -> None:
            if not self.success:
                message = self.error or "Agent execution failed"
                raise AssertionError(message)

        self._capture_assertion(
            "assert_success",
            expected=True,
            actual=self.success,
            assertion=evaluate,
        )

    def assert_tool_called(
        self,
        tool_name: str,
        server: str | None = None,
        *,
        status: StatusFilter = None,
        arguments: Mapping[str, Any] | None = None,
        argument_predicate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self._capture_assertion(
            "assert_tool_called",
            expected={
                "server": server,
                "tool_name": tool_name,
                "status": status,
                "arguments": arguments,
            },
            actual=[call.model_dump(mode="json") for call in self.tool_calls],
            assertion=lambda: self._engine().assert_tool_called(
                tool_name,
                server=server,
                status=status,
                arguments=arguments,
                argument_predicate=argument_predicate,
            ),
        )

    def assert_tool_not_called(self, tool_name: str, server: str | None = None) -> None:
        self._capture_assertion(
            "assert_tool_not_called",
            expected={"server": server, "tool_name": tool_name, "called": False},
            actual=[call.model_dump(mode="json") for call in self.tool_calls],
            assertion=lambda: self._engine().assert_tool_not_called(tool_name, server=server),
        )

    def assert_tool_order(
        self,
        *,
        before: tuple[str | None, str],
        after: tuple[str | None, str],
        status: StatusFilter = None,
        before_status: StatusFilter = None,
        after_status: StatusFilter = None,
    ) -> None:
        self._capture_assertion(
            "assert_tool_order",
            expected={"before": before, "after": after},
            actual=[call.qualified_name for call in self.tool_calls],
            assertion=lambda: self._engine().assert_tool_order(
                before=before,
                after=after,
                status=status,
                before_status=before_status,
                after_status=after_status,
            ),
        )

    def assert_tool_sequence(
        self,
        sequence: Sequence[WorkflowStep],
        *,
        allow_additional_read_tools: bool = False,
        status: StatusFilter = None,
    ) -> None:
        self._capture_assertion(
            "assert_tool_sequence",
            expected=[str(step) for step in sequence],
            actual=[call.qualified_name for call in self.tool_calls],
            assertion=lambda: self._engine().assert_tool_sequence(
                sequence,
                allow_additional_read_tools=allow_additional_read_tools,
                status=status,
            ),
        )

    def assert_read_before_write(
        self,
        *,
        read_tool: tuple[str | None, str],
        write_tool: tuple[str | None, str],
    ) -> None:
        self._capture_assertion(
            "assert_read_before_write",
            expected={"read_before": read_tool, "write": write_tool},
            actual=[call.qualified_name for call in self.tool_calls],
            assertion=lambda: self._engine().assert_read_before_write(
                read_tool=read_tool,
                write_tool=write_tool,
            ),
        )

    def assert_tool_call_count(
        self,
        tool_name: str,
        *,
        server: str | None = None,
        exact: int | None = None,
        min_calls: int | None = None,
        max_calls: int | None = None,
        status: ToolCallStatus | set[ToolCallStatus] | None = None,
        arguments: Mapping[str, Any] | None = None,
        argument_predicate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        matching_count = len(
            self._engine().matching_calls(
                tool_name,
                server=server,
                status=status,
                arguments=arguments,
                argument_predicate=argument_predicate,
            )
        )
        self._capture_assertion(
            "assert_tool_call_count",
            expected={"exact": exact, "min_calls": min_calls, "max_calls": max_calls},
            actual=matching_count,
            assertion=lambda: self._engine().assert_tool_call_count(
                tool_name,
                server=server,
                exact=exact,
                min_calls=min_calls,
                max_calls=max_calls,
                status=status,
                arguments=arguments,
                argument_predicate=argument_predicate,
            ),
        )

    def assert_max_workflow_steps(self, maximum: int) -> None:
        self._capture_assertion(
            "assert_max_workflow_steps",
            expected={"maximum": maximum},
            actual=len(self.tool_calls),
            assertion=lambda: self._engine().assert_max_workflow_steps(maximum),
        )

    def assert_max_tool_attempts(
        self,
        maximum: int,
        *,
        tool_name: str | None = None,
        server: str | None = None,
    ) -> None:
        attempts = [
            call.attempt
            for call in self.tool_calls
            if tool_name is None or call.matches(tool_name, server)
        ]
        self._capture_assertion(
            "assert_max_tool_attempts",
            expected={"maximum": maximum, "server": server, "tool_name": tool_name},
            actual=attempts,
            assertion=lambda: self._engine().assert_max_tool_attempts(
                maximum,
                tool_name=tool_name,
                server=server,
            ),
        )

    def assert_max_retries(
        self,
        maximum: int,
        *,
        tool_name: str | None = None,
        server: str | None = None,
    ) -> None:
        attempts = [
            call.attempt
            for call in self.tool_calls
            if tool_name is None or call.matches(tool_name, server)
        ]
        self._capture_assertion(
            "assert_max_retries",
            expected={"maximum": maximum, "server": server, "tool_name": tool_name},
            actual=[max(attempt - 1, 0) for attempt in attempts],
            assertion=lambda: self._engine().assert_max_retries(
                maximum,
                tool_name=tool_name,
                server=server,
            ),
        )

    def assert_no_failed_tool_calls(
        self,
        tool_name: str | None = None,
        *,
        server: str | None = None,
    ) -> None:
        self._capture_assertion(
            "assert_no_failed_tool_calls",
            expected={"failed_calls": 0, "server": server, "tool_name": tool_name},
            actual=[call.model_dump(mode="json") for call in self.tool_calls],
            assertion=lambda: self._engine().assert_no_failed_tool_calls(
                tool_name,
                server=server,
            ),
        )

    def assert_read_only(self) -> None:
        self._capture_assertion(
            "assert_read_only",
            expected={"write_calls": 0},
            actual=[call.model_dump(mode="json") for call in self.tool_calls],
            assertion=lambda: self._engine().assert_read_only(),
        )

    def assert_no_duplicate_tool_writes(self) -> None:
        self._capture_assertion(
            "assert_no_duplicate_tool_writes",
            expected={"duplicate_writes": 0},
            actual=[call.model_dump(mode="json") for call in self.tool_calls],
            assertion=lambda: self._engine().assert_no_duplicate_tool_writes(),
        )

    def assert_write_tool_called_once(
        self,
        *,
        server: str | None,
        tool: str,
    ) -> None:
        self._capture_assertion(
            "assert_write_tool_called_once",
            expected={"server": server, "tool": tool, "count": 1},
            actual=[
                call.model_dump(mode="json")
                for call in self.tool_calls
                if call.matches(tool, server)
            ],
            assertion=lambda: self._engine().assert_write_tool_called_once(
                server=server,
                tool=tool,
            ),
        )

    async def assert_score(self, scorer: Scorer, *, min_score: float) -> Score:
        """Score this result and require ``score.value >= min_score``."""
        from agent_test_kit.scoring import evaluate_score, validate_unit_interval

        validate_unit_interval("min_score", min_score)
        score = await evaluate_score(scorer, self)

        def evaluate() -> None:
            if score.value < min_score:
                detail = f" ({score.reason})" if score.reason else ""
                raise AssertionError(
                    f"Expected {scorer.name} score >= {min_score:.2f}. "
                    f"Observed: {score.value:.2f}{detail}"
                )

        self._capture_assertion(
            "assert_score",
            expected={"scorer": scorer.name, "min_score": min_score},
            actual={"score": score.value, "reason": score.reason, "details": score.details},
            assertion=evaluate,
        )
        return score

    @classmethod
    def from_api_response(
        cls,
        payload: dict[str, Any],
        *,
        run_context: RunContext | None = None,
    ) -> AgentExecutionResult:
        trace_payload = payload.get("trace")
        if isinstance(trace_payload, dict):
            trace = AgentTrace.from_payload(trace_payload)
        else:
            trace = AgentTrace.from_payload(payload)

        run_id = str(payload.get("run_id") or (run_context.run_id if run_context else ""))
        return cls(
            success=bool(payload.get("success", False)),
            run_id=run_id,
            trace_id=str(
                payload.get("trace_id") or (run_context.trace_id if run_context else "") or None
            )
            or None,
            correlation_id=str(
                payload.get("correlation_id")
                or (run_context.correlation_id if run_context else "")
                or None
            )
            or None,
            response=payload.get("response"),
            error=payload.get("error"),
            trace=trace,
            started_at=_parse_datetime(payload.get("started_at")),
            completed_at=_parse_datetime(payload.get("completed_at")),
            duration_ms=payload.get("duration_ms"),
        )


class AgentFlowResult(AgentExecutionResult):
    """Alias for multi-step agent workflow results."""

    steps: list[AgentExecutionResult] = Field(default_factory=list)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    return None


def utc_now() -> datetime:
    return datetime.now(UTC)
