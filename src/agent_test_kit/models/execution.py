"""Agent execution result models with workflow assertions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent_test_kit.models.run_context import RunContext
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

if TYPE_CHECKING:
    from agent_test_kit.assertions.flow import FlowAssertionEngine


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

    model_config = {"arbitrary_types_allowed": True}

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.trace.tool_calls

    def _engine(self) -> FlowAssertionEngine:
        from agent_test_kit.assertions.flow import FlowAssertionEngine

        return FlowAssertionEngine(self)

    def assert_success(self) -> None:
        if not self.success:
            message = self.error or "Agent execution failed"
            raise AssertionError(message)

    def assert_tool_called(self, tool_name: str, server: str | None = None) -> None:
        self._engine().assert_tool_called(tool_name, server=server)

    def assert_tool_not_called(self, tool_name: str, server: str | None = None) -> None:
        self._engine().assert_tool_not_called(tool_name, server=server)

    def assert_tool_order(
        self,
        *,
        before: tuple[str | None, str],
        after: tuple[str | None, str],
    ) -> None:
        self._engine().assert_tool_order(before=before, after=after)

    def assert_tool_sequence(
        self,
        sequence: list[tuple[str | None, str]],
        *,
        allow_additional_read_tools: bool = False,
    ) -> None:
        self._engine().assert_tool_sequence(
            sequence,
            allow_additional_read_tools=allow_additional_read_tools,
        )

    def assert_read_before_write(
        self,
        *,
        read_tool: tuple[str | None, str],
        write_tool: tuple[str | None, str],
    ) -> None:
        self._engine().assert_read_before_write(
            read_tool=read_tool,
            write_tool=write_tool,
        )

    def assert_no_duplicate_tool_writes(self) -> None:
        self._engine().assert_no_duplicate_tool_writes()

    def assert_write_tool_called_once(
        self,
        *,
        server: str | None,
        tool: str,
    ) -> None:
        self._engine().assert_write_tool_called_once(server=server, tool=tool)

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
