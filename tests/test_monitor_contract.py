"""The monitor contract stays aligned with release readiness."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agent_test_kit.models.report import (
    AgentTestRunReport,
    EvalCheckReport,
    GuardrailCheckReport,
    ScenarioReport,
    ScenarioStatus,
)
from agent_test_kit.reporting.monitor_contract import MONITOR_SCHEMA, monitor_summary

pytestmark = pytest.mark.agent_unit

_NOW = datetime(2026, 11, 8, tzinfo=UTC)


def _scenario(nodeid: str, status: ScenarioStatus = "passed", **fields: Any) -> ScenarioReport:
    return ScenarioReport(
        name=nodeid.rsplit("::", 1)[-1],
        nodeid=nodeid,
        passed=status == "passed",
        status=status,
        duration_ms=1,
        **fields,
    )


def _report(*scenarios: ScenarioReport, **fields: Any) -> AgentTestRunReport:
    report = AgentTestRunReport(
        run_id="run_now",
        agent_id="pr-review",
        environment="ci",
        started_at=_NOW,
        completed_at=_NOW,
        scenarios=list(scenarios),
        **fields,
    )
    report.finalize_metrics()
    return report


def test_unit_pass_is_go() -> None:
    summary = monitor_summary(_report(_scenario("tests/test_review.py::test_mock")))

    assert summary.verdict == "go"
    assert summary.phase == "unit"
    assert summary.pass_rate == 1.0
    assert summary.as_dict()["schema"] == MONITOR_SCHEMA


def test_failed_scenario_is_no_go() -> None:
    summary = monitor_summary(_report(_scenario("tests/test_review.py::test_mock", "failed")))

    assert summary.verdict == "no_go"
    assert summary.failed == 1
    assert any("failed or errored" in reason for reason in summary.blocking)


def test_live_marker_selects_the_post_deploy_phase() -> None:
    summary = monitor_summary(
        _report(_scenario("tests/agent_e2e/test_live.py::test_health", markers=["agent_e2e"]))
    )

    assert summary.phase == "post_deploy"
    assert summary.verdict == "go"


def test_eval_and_guardrail_failures_are_listed_without_changing_a_green_scenario() -> None:
    summary = monitor_summary(
        _report(
            _scenario(
                "tests/test_review.py::test_mock",
                evals=[
                    EvalCheckReport(name="terms", passed=False, score=0.2, threshold=0.8),
                ],
                guardrails=[GuardrailCheckReport(name="no-secrets", passed=False)],
            )
        )
    )

    assert summary.verdict == "go"
    assert summary.eval_failures == ("tests/test_review.py::test_mock: terms",)
    assert summary.guardrail_failures == ("tests/test_review.py::test_mock: no-secrets",)


def test_security_failure_blocks() -> None:
    summary = monitor_summary(
        _report(_scenario("tests/test_review.py::test_mock", security_failure=True))
    )

    assert summary.verdict == "no_go"
    assert summary.security_failures == 1
