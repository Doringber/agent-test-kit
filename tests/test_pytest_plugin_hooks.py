"""Additional pytest plugin hook coverage."""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.plugin import pytest_plugin
from agent_test_kit.reporting.json_report import JsonReportWriter


@pytest.mark.agent_unit
def test_record_scenario_from_report(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="demo"),
        output_path=tmp_path / "report.json",
    )
    state = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=writer,
        results={
            "tests/demo.py::test_demo": AgentExecutionResult(success=True, run_id="run_1"),
        },
    )

    item = MagicMock()
    item.nodeid = "tests/demo.py::test_demo"
    item.name = "test_demo"
    marker = MagicMock()
    marker.name = "agent_unit"
    item.iter_markers.return_value = [marker]

    setup_report = MagicMock(passed=True, failed=False, skipped=False, duration=0.05)
    setup_report.when = "setup"
    setup_report.longrepr = None
    call_report = MagicMock(passed=True, failed=False, skipped=False, duration=0.25)
    call_report.when = "call"
    call_report.longrepr = None
    teardown_report = MagicMock(passed=True, failed=False, skipped=False, duration=0.1)
    teardown_report.when = "teardown"
    teardown_report.longrepr = None

    pytest_plugin._record_scenario_from_reports(
        state,
        item,
        {
            "setup": setup_report,
            "call": call_report,
            "teardown": teardown_report,
        },
    )
    assert len(writer.scenarios) == 1
    assert writer.scenarios[0].run_id == "run_1"
    assert writer.scenarios[0].duration_ms == 400


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    ("phase", "skipped", "error"),
    [
        ("call", True, None),
        ("teardown", False, "cleanup exploded"),
    ],
)
def test_record_scenario_aggregates_skip_and_teardown_failure(
    tmp_path: Path,
    phase: str,
    skipped: bool,
    error: str | None,
) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="demo"),
        output_path=tmp_path / "report.json",
    )
    state = pytest_plugin.PluginState(agent_config=AgentTestConfig(), json_writer=writer)
    item = MagicMock()
    item.nodeid = "tests/demo.py::test_demo"
    item.name = "test_demo"
    item.iter_markers.return_value = []
    reports: dict[str, MagicMock] = {}
    for report_phase in ("setup", "call", "teardown"):
        is_target = report_phase == phase
        report = MagicMock()
        report.when = report_phase
        report.duration = 0.01
        report.skipped = is_target and skipped
        report.failed = is_target and error is not None
        report.passed = not report.skipped and not report.failed
        report.longrepr = error
        reports[report_phase] = report

    pytest_plugin._record_scenario_from_reports(state, item, reports)

    scenario = writer.scenarios[0]
    assert not scenario.passed
    assert scenario.skipped is skipped
    assert scenario.error_message == error


@pytest.mark.agent_unit
def test_pytest_sessionfinish_writes_report(tmp_path: Path) -> None:
    config = MagicMock()
    output = tmp_path / "report.json"
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=JsonReportWriter(
            config=AgentTestConfig(),
            output_path=output,
        ),
    )
    config.getoption.return_value = None

    session = MagicMock()
    session.config = config

    pytest_plugin.pytest_sessionfinish(session, 0)
    assert output.exists()


@pytest.mark.agent_unit
def test_pytest_sessionfinish_does_not_warn_for_html() -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=None,
    )
    config.getoption.return_value = "reports/pending.html"

    session = MagicMock()
    session.config = config

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pytest_plugin.pytest_sessionfinish(session, 0)
    assert caught == []


@pytest.mark.agent_unit
def test_makereport_hook_collects_all_lifecycle_phases(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(),
        output_path=tmp_path / "report.json",
    )
    config = MagicMock()
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=writer,
    )
    item = MagicMock()
    item.config = config
    item.nodeid = "tests/demo.py::test_demo"
    item.name = "test_demo"
    item.iter_markers.return_value = []

    for phase in ("setup", "call", "teardown"):
        report = MagicMock()
        report.when = phase
        report.duration = 0.01
        report.passed = True
        report.failed = False
        report.skipped = False
        report.longrepr = None
        hook = pytest_plugin.pytest_runtest_makereport(item, MagicMock())
        next(hook)
        outcome = MagicMock()
        outcome.get_result.return_value = report
        with pytest.raises(StopIteration):
            hook.send(outcome)

    assert len(writer.scenarios) == 1


@pytest.mark.agent_unit
def test_store_execution_result_no_state() -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    pytest_plugin.store_execution_result(
        config,
        "node",
        AgentExecutionResult(success=True, run_id="run_1"),
    )
