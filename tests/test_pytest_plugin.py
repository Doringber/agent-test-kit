"""Pytest plugin integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.plugin import pytest_plugin
from agent_test_kit.reporting.json_report import JsonReportWriter


@pytest.mark.agent_unit
def test_pytest_configure_creates_json_writer(tmp_path: Path) -> None:
    config = MagicMock()
    config.getoption.return_value = str(tmp_path / "report.json")
    config.stash = pytest.Stash()

    pytest_plugin.pytest_configure(config)

    state = config.stash[pytest_plugin._STASH_KEY]
    assert isinstance(state.agent_config, AgentTestConfig)
    assert state.json_writer is not None


@pytest.mark.agent_unit
def test_store_execution_result() -> None:
    config = MagicMock()
    config.stash = pytest.Stash()
    config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=None,
    )
    result = AgentExecutionResult(success=True, run_id="run_abc")
    pytest_plugin.store_execution_result(config, "tests/test_x.py::test_x", result)
    stored = config.stash[pytest_plugin._STASH_KEY].results["tests/test_x.py::test_x"]
    assert stored.run_id == "run_abc"


@pytest.mark.agent_unit
def test_json_report_roundtrip(tmp_path: Path) -> None:
    output = tmp_path / "agent-results.json"
    writer = JsonReportWriter(config=AgentTestConfig(agent_id="demo"), output_path=output)
    writer.record_scenario(
        name="demo",
        nodeid="tests/demo.py::test_demo",
        passed=True,
        duration_ms=50,
        markers=["agent_unit"],
    )
    writer.write()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["agent_id"] == "demo"
    assert payload["metrics"]["passed"] == 1


@pytest.mark.agent_unit
def test_agent_client_fixture_available(agent_client: object) -> None:
    from agent_test_kit import AgentClient

    assert isinstance(agent_client, AgentClient)


@pytest.mark.agent_unit
def test_cursor_fixture_forces_agent_endpoint_and_records_current_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_TEST_BASE_URL", raising=False)
    config = AgentTestConfig(base_url="http://localhost:8080")
    request = MagicMock()
    request.config.stash = pytest.Stash()
    request.node.nodeid = "tests/demo.py::test_demo"
    request.config.stash[pytest_plugin._STASH_KEY] = pytest_plugin.PluginState(
        agent_config=config,
        json_writer=None,
    )

    client = pytest_plugin.cursor_agent_client.__wrapped__(config, request)
    result = AgentExecutionResult(success=True, run_id="run_fixture")
    assert client.config.execute_url == "http://localhost:8080/agent"

    client._on_result(result)

    state = request.config.stash[pytest_plugin._STASH_KEY]
    assert state.results[request.node.nodeid] is result


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_agent_cleanup_fixture_always_executes_callbacks() -> None:
    cleaned: list[str] = []
    fixture_generator = pytest_plugin.agent_cleanup.__wrapped__()
    manager = await anext(fixture_generator)
    manager.register(lambda: cleaned.append("done"))

    await fixture_generator.aclose()

    assert cleaned == ["done"]


@pytest.mark.agent_unit
def test_agent_cleanup_fixture_supports_pytest_asyncio_strict_mode(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeini(
        """
[pytest]
asyncio_mode = strict
asyncio_default_fixture_loop_scope = function
"""
    )
    pytester.makepyfile(
        """
import pytest


@pytest.mark.asyncio
async def test_cleanup(agent_cleanup):
    cleaned = []
    agent_cleanup.register(lambda: cleaned.append("done"))
    assert cleaned == []
"""
    )

    result = pytester.runpytest("-q")

    result.assert_outcomes(passed=1)
