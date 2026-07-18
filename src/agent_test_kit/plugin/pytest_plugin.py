"""Pytest plugin for agent-test-kit."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_test_kit.client.agent_client import AgentClient
from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.reporting.json_report import JsonReportWriter


@dataclass
class PluginState:
    agent_config: AgentTestConfig
    json_writer: JsonReportWriter | None
    results: dict[str, AgentExecutionResult] = field(default_factory=dict)


_STASH_KEY = pytest.StashKey[PluginState]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("agent-test-kit")
    group.addoption(
        "--agent-report-json",
        action="store",
        default=None,
        help="Write agent test JSON report to this path",
    )
    group.addoption(
        "--agent-report-html",
        action="store",
        default=None,
        help="Write agent test HTML report to this path (Phase 4)",
    )


def pytest_configure(config: pytest.Config) -> None:
    agent_config = AgentTestConfig()
    json_path = config.getoption("--agent-report-json")
    writer: JsonReportWriter | None = None
    if json_path:
        writer = JsonReportWriter(config=agent_config, output_path=Path(json_path))
    config.stash[_STASH_KEY] = PluginState(
        agent_config=agent_config,
        json_writer=writer,
    )


@pytest.fixture
def agent_test_config(request: pytest.FixtureRequest) -> AgentTestConfig:
    return request.config.stash[_STASH_KEY].agent_config


@pytest.fixture
def agent_client(agent_test_config: AgentTestConfig) -> AgentClient:
    return AgentClient(agent_test_config)


@pytest.fixture
def agent_execution_result(request: pytest.FixtureRequest) -> AgentExecutionResult | None:
    return request.config.stash[_STASH_KEY].results.get(request.node.nodeid)


def _record_scenario_from_report(
    state: PluginState,
    item: pytest.Item,
    report: pytest.TestReport,
) -> None:
    writer = state.json_writer
    if writer is None:
        return

    duration_ms = int(report.duration * 1000)
    markers = [marker.name for marker in item.iter_markers()]
    stored_result = state.results.get(item.nodeid)
    extra: dict[str, Any] = {}
    if stored_result is not None:
        extra["run_id"] = stored_result.run_id
        extra["tool_calls"] = stored_result.tool_calls

    writer.record_scenario(
        name=item.name,
        nodeid=item.nodeid,
        passed=report.passed,
        duration_ms=duration_ms,
        markers=markers,
        error_message=str(report.longrepr) if report.failed else None,
        extra=extra,
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return

    state = item.config.stash.get(_STASH_KEY, None)
    if state is None:
        return

    _record_scenario_from_report(state, item, report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    state = session.config.stash.get(_STASH_KEY, None)
    if state is None:
        return
    if state.json_writer is not None:
        state.json_writer.write()

    html_path = session.config.getoption("--agent-report-html")
    if html_path:
        warnings.warn(
            f"HTML report requested at {html_path} but is not yet implemented (Phase 4).",
            stacklevel=1,
        )


def store_execution_result(
    config: pytest.Config,
    nodeid: str,
    result: AgentExecutionResult,
) -> None:
    """Allow tests to attach an execution result for reporting."""
    state = config.stash.get(_STASH_KEY, None)
    if state is None:
        return
    state.results[nodeid] = result
