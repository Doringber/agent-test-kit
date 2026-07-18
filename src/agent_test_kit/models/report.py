"""Versioned agent test run report schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent_test_kit._version import __version__
from agent_test_kit.models.tool_call import ToolCall


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
    evidence_links: list[str] = Field(default_factory=list)


class ScenarioReport(BaseModel):
    """Report for one pytest scenario."""

    name: str
    nodeid: str
    passed: bool
    duration_ms: int
    markers: list[str] = Field(default_factory=list)
    run_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    assertions: list[AssertionReport] = Field(default_factory=list)
    side_effect_verifications: list[SideEffectVerificationReport] = Field(default_factory=list)
    error_message: str | None = None


class RunMetrics(BaseModel):
    """Aggregate metrics for a test run."""

    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    total_tool_calls: int = 0
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
        self.metrics.passed = sum(1 for scenario in self.scenarios if scenario.passed)
        self.metrics.failed = self.metrics.total_scenarios - self.metrics.passed
        self.metrics.total_tool_calls = sum(len(scenario.tool_calls) for scenario in self.scenarios)
