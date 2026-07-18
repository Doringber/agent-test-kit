"""Tool call and trace status models."""

from __future__ import annotations

from enum import StrEnum


class ToolCallStatus(StrEnum):
    """Execution status for a single tool invocation."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class ToolOperationKind(StrEnum):
    """Whether a tool performs a read or write against external systems."""

    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"
