"""Report model tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_test_kit.models.report import AgentTestRunReport, ScenarioReport


@pytest.mark.agent_unit
def test_report_finalize_metrics() -> None:
    now = datetime.now(UTC)
    report = AgentTestRunReport(
        run_id="run_1",
        agent_id="agent",
        environment="test",
        started_at=now,
        completed_at=now,
        scenarios=[
            ScenarioReport(
                name="pass",
                nodeid="n1",
                passed=True,
                duration_ms=10,
            ),
            ScenarioReport(
                name="fail",
                nodeid="n2",
                passed=False,
                duration_ms=20,
            ),
        ],
    )
    report.finalize_metrics()
    assert report.metrics.total_scenarios == 2
    assert report.metrics.passed == 1
    assert report.metrics.failed == 1
