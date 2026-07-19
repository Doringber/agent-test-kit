"""Versioned agent test run report schema."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from agent_test_kit._version import __version__
from agent_test_kit.models.enums import ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import TraceEvent

ScenarioStatus = Literal["passed", "failed", "skipped", "error"]


class AssertionReport(BaseModel):
    """Record of a single assertion evaluated during a scenario."""

    name: str
    passed: bool
    expected: Any | None = None
    actual: Any | None = None
    message: str | None = None


class SideEffectVerificationReport(BaseModel):
    """Outcome of an external side-effect verifier."""

    verifier_name: str
    passed: bool
    message: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_links: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    error_type: str | None = None
    timed_out: bool = False


class ScenarioReport(BaseModel):
    """Report for one pytest scenario."""

    name: str
    nodeid: str
    passed: bool
    skipped: bool = False
    status: ScenarioStatus | None = None
    duration_ms: int
    markers: list[str] = Field(default_factory=list)
    run_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    timeline: list[TraceEvent] = Field(default_factory=list)
    assertions: list[AssertionReport] = Field(default_factory=list)
    side_effect_verifications: list[SideEffectVerificationReport] = Field(default_factory=list)
    error_message: str | None = None
    retry_count: int = 0
    token_usage: int | None = None
    estimated_cost_usd: float | None = None
    duplicate_write_count: int = 0
    security_failure: bool = False

    @model_validator(mode="after")
    def derive_status(self) -> ScenarioReport:
        """Keep legacy passed/skipped fields consistent with explicit status."""
        if self.status is None:
            self.status = "skipped" if self.skipped else ("passed" if self.passed else "failed")
        self.passed = self.status == "passed"
        self.skipped = self.status == "skipped"
        return self


class RunMetrics(BaseModel):
    """Aggregate metrics for a test run."""

    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total_tool_calls: int = 0
    total_retries: int = 0
    total_token_usage: int | None = None
    estimated_cost_usd: float | None = None
    duplicate_write_count: int = 0
    security_failure_count: int = 0


class AgentTestRunReport(BaseModel):
    """Versioned report emitted after a pytest session."""

    schema_version: str = "1.0"
    framework_version: str = Field(default_factory=lambda: __version__)
    run_id: str
    repository: str | None = None
    branch: str | None = None
    commit: str | None = None
    pipeline_id: str | None = None
    agent_id: str
    agent_version: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    environment: str
    started_at: datetime
    completed_at: datetime
    scenarios: list[ScenarioReport] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)

    def finalize_metrics(self) -> None:
        self.metrics.total_scenarios = len(self.scenarios)
        self.metrics.passed = sum(1 for scenario in self.scenarios if scenario.status == "passed")
        self.metrics.failed = sum(1 for scenario in self.scenarios if scenario.status == "failed")
        self.metrics.skipped = sum(1 for scenario in self.scenarios if scenario.status == "skipped")
        self.metrics.errors = sum(1 for scenario in self.scenarios if scenario.status == "error")
        self.metrics.total_tool_calls = sum(len(scenario.tool_calls) for scenario in self.scenarios)
        self.metrics.total_retries = sum(scenario.retry_count for scenario in self.scenarios)
        token_values = [
            scenario.token_usage for scenario in self.scenarios if scenario.token_usage is not None
        ]
        self.metrics.total_token_usage = sum(token_values) if token_values else None
        cost_values = [
            scenario.estimated_cost_usd
            for scenario in self.scenarios
            if scenario.estimated_cost_usd is not None
        ]
        self.metrics.estimated_cost_usd = sum(cost_values) if cost_values else None
        self.metrics.duplicate_write_count = sum(
            scenario.duplicate_write_count for scenario in self.scenarios
        )
        self.metrics.security_failure_count = sum(
            1 for scenario in self.scenarios if scenario.security_failure
        )


def count_duplicate_writes(tool_calls: list[ToolCall]) -> int:
    """Count repeated writes beyond the first invocation per tool."""
    counts = Counter(
        call.qualified_name for call in tool_calls if call.operation_kind == ToolOperationKind.WRITE
    )
    return sum(count - 1 for count in counts.values() if count > 1)
