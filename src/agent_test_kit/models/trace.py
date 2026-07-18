"""Agent execution trace models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent_test_kit.models.tool_call import ToolCall


class TraceEvent(BaseModel):
    """Single event in an agent execution timeline."""

    timestamp: datetime
    label: str
    event_type: str
    server: str | None = None
    tool_name: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTrace(BaseModel):
    """Normalized trace returned by an agent execution."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    token_usage: int | None = None
    estimated_cost_usd: float | None = None
    model: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> AgentTrace:
        if not payload:
            return cls()
        tool_calls_raw = payload.get("tool_calls", [])
        tool_calls = [
            ToolCall.model_validate(item) if isinstance(item, dict) else item
            for item in tool_calls_raw
        ]
        events_raw = payload.get("events", [])
        events = [
            TraceEvent.model_validate(item) if isinstance(item, dict) else item
            for item in events_raw
        ]
        return cls(
            tool_calls=tool_calls,
            events=events,
            token_usage=payload.get("token_usage"),
            estimated_cost_usd=payload.get("estimated_cost_usd"),
            model=payload.get("model"),
        )
