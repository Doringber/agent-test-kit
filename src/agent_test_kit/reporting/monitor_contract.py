"""Stable slice of a kit report for the twice-daily agent monitor.

The monitor does not import this package. It reads the same keys from the
JSON written by ``--agent-report-json``, or from :func:`monitor_summary`.
Keep the keys stable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from agent_test_kit.models.report import AgentTestRunReport
from agent_test_kit.reporting.readiness import evaluate_readiness

MONITOR_SCHEMA = "agent-test-kit.monitor/v1"
Phase = Literal["unit", "post_deploy"]


@dataclass(frozen=True, slots=True)
class MonitorSummary:
    """GO / NO-GO evidence the monitor renders next to production metrics."""

    agent_id: str
    run_id: str
    environment: str
    phase: Phase
    verdict: Literal["go", "no_go"]
    blocking: tuple[str, ...]
    notes: tuple[str, ...]
    scenarios: int
    passed: int
    failed: int
    pass_rate: float | None
    security_failures: int
    eval_failures: tuple[str, ...]
    guardrail_failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON object the monitor accepts."""
        payload = asdict(self)
        payload["schema"] = MONITOR_SCHEMA
        return payload


def monitor_summary(report: AgentTestRunReport) -> MonitorSummary:
    """Summarize a kit report the way the twice-daily monitor will read it.

    The verdict is the kit's release readiness. Failed evals and guardrails
    are listed even when the scenario itself stayed green.
    """
    readiness = report.readiness if report.readiness is not None else evaluate_readiness(report)
    executed = [scenario for scenario in report.scenarios if scenario.status != "skipped"]
    passed = sum(1 for scenario in executed if scenario.status == "passed")
    failed = sum(1 for scenario in executed if scenario.status in {"failed", "error"})
    phase: Phase = (
        "post_deploy"
        if any("agent_e2e" in scenario.markers for scenario in report.scenarios)
        else "unit"
    )
    return MonitorSummary(
        agent_id=report.agent_id,
        run_id=report.run_id,
        environment=report.environment,
        phase=phase,
        verdict=readiness.verdict,
        blocking=tuple(readiness.blocking),
        notes=tuple(readiness.notes),
        scenarios=len(executed),
        passed=passed,
        failed=failed,
        pass_rate=(passed / len(executed)) if executed else None,
        security_failures=sum(1 for scenario in executed if scenario.security_failure),
        eval_failures=tuple(
            f"{scenario.nodeid}: {item.name}"
            for scenario in executed
            for item in scenario.evals
            if not item.passed
        ),
        guardrail_failures=tuple(
            f"{scenario.nodeid}: {item.name}"
            for scenario in executed
            for item in scenario.guardrails
            if not item.passed
        ),
    )
