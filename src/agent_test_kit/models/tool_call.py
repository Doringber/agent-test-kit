"""Normalized tool call model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind


class ToolCall(BaseModel):
    """Normalized representation of a single MCP tool invocation."""

    id: str | None = None
    server: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any | None = None
    status: ToolCallStatus = ToolCallStatus.SUCCESS
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    attempt: int = 1
    parent_step_id: str | None = None
    operation_kind: ToolOperationKind = ToolOperationKind.UNKNOWN

    @property
    def qualified_name(self) -> tuple[str | None, str]:
        return (self.server, self.name)

    @property
    def is_read(self) -> bool:
        return self.operation_kind == ToolOperationKind.READ

    @property
    def is_write(self) -> bool:
        return self.operation_kind == ToolOperationKind.WRITE

    @property
    def is_success(self) -> bool:
        return self.status == ToolCallStatus.SUCCESS

    def matches(self, tool_name: str, server: str | None = None) -> bool:
        if self.name != tool_name:
            return False
        return not (server is not None and self.server != server)
