"""JSON report generation for pytest runs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.report import AgentTestRunReport, ScenarioReport
from agent_test_kit.reporting.redaction import redact_value


class JsonReportWriter:
    """Collects scenario results and writes a versioned JSON report."""

    def __init__(
        self,
        *,
        config: AgentTestConfig,
        output_path: Path,
    ) -> None:
        self.config = config
        self.output_path = output_path
        self.run_id = f"pytest_{uuid.uuid4().hex[:12]}"
        self.started_at = datetime.now(UTC)
        self.scenarios: list[ScenarioReport] = []

    def record_scenario(
        self,
        *,
        name: str,
        nodeid: str,
        passed: bool,
        duration_ms: int,
        markers: list[str],
        error_message: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        extra = extra or {}
        self.scenarios.append(
            ScenarioReport(
                name=name,
                nodeid=nodeid,
                passed=passed,
                duration_ms=duration_ms,
                markers=markers,
                run_id=extra.get("run_id"),
                tool_calls=extra.get("tool_calls", []),
                error_message=error_message,
            )
        )

    def build_report(self) -> AgentTestRunReport:
        report = AgentTestRunReport(
            run_id=self.run_id,
            repository=self.config.repository,
            branch=self.config.branch,
            commit=self.config.commit,
            pipeline_id=self.config.pipeline_id,
            agent_id=self.config.agent_id,
            agent_version=self.config.agent_version,
            model=self.config.model,
            prompt_version=self.config.prompt_version,
            environment=self.config.environment,
            started_at=self.started_at,
            completed_at=datetime.now(UTC),
            scenarios=self.scenarios,
        )
        report.finalize_metrics()
        return report

    def write(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.build_report()
        payload = redact_value(report.model_dump(mode="json"))
        self.output_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return self.output_path
