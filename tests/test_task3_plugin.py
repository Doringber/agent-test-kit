"""Task 3 pytest plugin report attachment tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.report import AgentTestRunReport
from agent_test_kit.plugin import pytest_plugin
from agent_test_kit.verifiers import VerificationResult, VerificationSummary


@pytest.mark.agent_unit
def test_scenario_recorder_attaches_execution_and_verifier_results() -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=None,
    )
    recorder = pytest_plugin.ScenarioResultRecorder(config, "tests/x.py::test_x")
    execution = AgentExecutionResult(success=True, run_id="run_attached")
    summary = VerificationSummary(
        (
            VerificationResult(
                verifier_name="database",
                passed=True,
                evidence={"url": "https://evidence.example/1"},
            ),
        )
    )

    recorder.attach_execution_result(execution)
    recorder.attach_verifier_results(summary)

    state = config.stash[pytest_plugin._STASH_KEY]
    assert state.results[recorder.nodeid] is execution
    assert state.verification_results[recorder.nodeid][0].verifier_name == "database"


@pytest.mark.agent_unit
def test_sessionfinish_writes_html_report_instead_of_warning(tmp_path: Path) -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    writer = pytest_plugin.JsonReportWriter(
        config=AgentTestConfig(agent_id="plugin-agent"),
        output_path=json_path,
    )
    writer.record_scenario(
        name="demo",
        nodeid="tests/demo.py::test_demo",
        passed=True,
        duration_ms=1,
        markers=[],
    )
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=writer,
        html_path=html_path,
    )
    session = MagicMock(config=config)

    pytest_plugin.pytest_sessionfinish(session, 0)

    assert json_path.exists()
    assert html_path.exists()
    assert "plugin-agent" in html_path.read_text(encoding="utf-8")


@pytest.mark.agent_unit
def test_sessionfinish_serializes_one_report_instance_to_both_formats(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    report = AgentTestRunReport(
        run_id="single-report",
        agent_id="plugin-agent",
        environment="test",
        started_at=now,
        completed_at=now,
    )
    json_writer = MagicMock()
    json_writer.build_report.return_value = report
    html_writer = MagicMock()
    monkeypatch.setattr(
        pytest_plugin,
        "HtmlReportWriter",
        MagicMock(return_value=html_writer),
    )
    config = MagicMock()
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=json_writer,
        html_path=tmp_path / "report.html",
    )

    pytest_plugin.pytest_sessionfinish(MagicMock(config=config), 0)

    json_writer.build_report.assert_called_once_with()
    json_writer.write.assert_called_once_with(report)
    html_writer.write.assert_called_once_with(report)
