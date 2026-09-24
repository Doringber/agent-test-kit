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
    options = {"--agent-report-json": str(tmp_path / "report.json")}
    config = MagicMock()
    config.getoption.side_effect = lambda name, default=None: options.get(name, default)
    config.stash = pytest.Stash()

    pytest_plugin.pytest_configure(config)

    state = config.stash[pytest_plugin._STASH_KEY]
    assert isinstance(state.agent_config, AgentTestConfig)
    assert state.json_writer is not None
    assert state.baseline_path is None
    assert state.enforce_readiness is False


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


@pytest.mark.agent_unit
def test_agent_report_html_includes_tool_flow_from_fixture(
    pytester: pytest.Pytester,
    tmp_path: Path,
) -> None:
    """Plugin CLI report must include tool flow when agent_client attaches results."""
    html_path = tmp_path / "flow-report.html"
    json_path = tmp_path / "flow-report.json"
    pytester.makeini(
        """
[pytest]
asyncio_mode = auto
"""
    )
    pytester.makeconftest(
        """
import httpx
import pytest
from agent_test_kit import AgentClient
from agent_test_kit.plugin import pytest_plugin


class _FakeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True,
            "run_id": "run_fixture_flow",
            "response": {"summary": "ok"},
            "trace": {
                "tool_calls": [
                    {
                        "server": "billing",
                        "name": "get_customer_invoices",
                        "operation_kind": "read",
                        "status": "success",
                    },
                ],
            },
        })


@pytest.fixture
def agent_client(agent_test_config, request):
    return AgentClient(
        agent_test_config,
        transport=_FakeTransport(),
        on_result=lambda result: pytest_plugin.store_execution_result(
            request.config,
            request.node.nodeid,
            result,
        ),
    )
"""
    )
    pytester.makepyfile(
        """
import pytest


@pytest.mark.asyncio
@pytest.mark.agent_unit
async def test_billing_flow(agent_client):
    result = await agent_client.execute({"account_id": 12345})
    result.assert_success()
"""
    )

    result = pytester.runpytest(
        f"--agent-report-json={json_path}",
        f"--agent-report-html={html_path}",
        "-q",
    )

    result.assert_outcomes(passed=1)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")

    assert payload["metrics"]["total_tool_calls"] == 1
    assert payload["scenarios"][0]["tool_calls"][0]["name"] == "get_customer_invoices"
    assert "flow-strip" in html
    assert "billing/get_customer_invoices" in html
    assert "flow-read" in html
