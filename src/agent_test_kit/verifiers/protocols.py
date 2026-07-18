"""Side-effect verification protocols (implemented by consumer repos)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agent_test_kit.models.execution import AgentExecutionResult


@dataclass
class VerificationContext:
    """Context passed to side-effect verifiers after agent execution."""

    run_id: str
    correlation_id: str | None
    execution_result: AgentExecutionResult
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Outcome of a side-effect verification."""

    passed: bool
    message: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SideEffectVerifier(Protocol):
    """Protocol implemented by consumer repositories."""

    name: str

    async def verify(self, context: VerificationContext) -> VerificationResult:
        """Verify real-world side effects independently of tool-call traces."""
        ...
