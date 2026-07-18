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

    report = MagicMock()
    report.passed = True
    report.duration = 0.25
    report.failed = False
    report.longrepr = None

    pytest_plugin._record_scenario_from_report(state, item, report)
    assert len(writer.scenarios) == 1
    assert writer.scenarios[0].run_id == "run_1"


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
def test_pytest_sessionfinish_html_warning() -> None:
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
    assert any("Phase 4" in str(item.message) for item in caught)


@pytest.mark.agent_unit
def test_store_execution_result_no_state() -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    pytest_plugin.store_execution_result(
        config,
        "node",
        AgentExecutionResult(success=True, run_id="run_1"),
    )
