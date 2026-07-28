"""Pytest plugin for agent-test-kit."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from agent_test_kit.cleanup.manager import CleanupManager
from agent_test_kit.client.agent_client import AgentClient
from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.client.cursor_agent_client import CursorAgentClient
from agent_test_kit.client.prompt_ai_helper_profiles import get_profile
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.report import ScenarioStatus
from agent_test_kit.reporting.html_report import HtmlReportWriter
from agent_test_kit.reporting.json_report import JsonReportWriter
from agent_test_kit.verifiers import (
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
    VerificationSummary,
    run_verifiers,
)


@dataclass
class PluginState:
    agent_config: AgentTestConfig
    json_writer: JsonReportWriter | None
    results: dict[str, AgentExecutionResult] = field(default_factory=dict)
    verification_results: dict[str, list[VerificationResult]] = field(default_factory=dict)
    phase_reports: dict[str, dict[str, pytest.TestReport]] = field(default_factory=dict)
    html_path: Path | None = None
    write_json: bool = True


_STASH_KEY = pytest.StashKey[PluginState]()


def pytest_configure(config: pytest.Config) -> None:
    agent_config = AgentTestConfig()
    profile_env = os.getenv("PROMPT_AI_HELPER_ENV", "").strip()
    if profile_env:
        profile = get_profile(profile_env)
        agent_config = agent_config.model_copy(
            update={
                "base_url": profile.base_url,
                "execute_path": profile.agent_path,
                "environment": profile.name,
                "agent_id": "prompt-ai-helper",
                "model": profile.model,
                "verify_ssl": profile.verify_ssl,
            }
        )
    json_path = config.getoption("--agent-report-json")
    html_path = config.getoption("--agent-report-html")
    writer: JsonReportWriter | None = None
    if json_path:
        writer = JsonReportWriter(config=agent_config, output_path=Path(json_path))
    elif html_path:
        writer = JsonReportWriter(
            config=agent_config,
            output_path=Path(html_path).with_suffix(".json"),
        )
    if writer is not None and profile_env:
        profile = get_profile(profile_env)
        writer.endpoint_profile = dict(profile.endpoint_rows())
        writer.expected_mcp_servers = list(profile.mcp_servers)
    config.stash[_STASH_KEY] = PluginState(
        agent_config=agent_config,
        json_writer=writer,
        html_path=Path(html_path) if html_path else None,
        write_json=bool(json_path),
    )


@dataclass(frozen=True, slots=True)
class ScenarioResultRecorder:
    """Consumer-facing attachment and verifier runner for the current test."""

    config: pytest.Config
    nodeid: str

    @property
    def execution_result(self) -> AgentExecutionResult | None:
        state = self.config.stash.get(_STASH_KEY, None)
        return state.results.get(self.nodeid) if state is not None else None

    def attach_execution_result(self, result: AgentExecutionResult) -> None:
        store_execution_result(self.config, self.nodeid, result)

    def attach_verifier_results(
        self,
        results: VerificationSummary | Sequence[VerificationResult],
    ) -> None:
        attach_verification_results(self.config, self.nodeid, results)

    async def verify(
        self,
        verifiers: Sequence[SideEffectVerifier],
        *,
        timeout_seconds: float = 10.0,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationSummary:
        result = self.execution_result
        if result is None:
            raise RuntimeError("Attach or execute an agent result before running verifiers")
        context = VerificationContext(
            run_id=result.run_id,
            correlation_id=result.correlation_id,
            execution_result=result,
            metadata=metadata or {},
        )
        summary = await run_verifiers(
            list(verifiers),
            context,
            timeout_seconds=timeout_seconds,
        )
        self.attach_verifier_results(summary)
        return summary


@pytest.fixture
def agent_test_config(request: pytest.FixtureRequest) -> AgentTestConfig:
    return request.config.stash[_STASH_KEY].agent_config


@pytest.fixture
def agent_client(
    agent_test_config: AgentTestConfig,
    request: pytest.FixtureRequest,
) -> AgentClient:
    return AgentClient(
        agent_test_config,
        on_result=lambda result: store_execution_result(
            request.config,
            request.node.nodeid,
            result,
        ),
    )


@pytest.fixture
def cursor_agent_client(
    agent_test_config: AgentTestConfig,
    request: pytest.FixtureRequest,
) -> CursorAgentClient:
    return CursorAgentClient(
        agent_test_config,
        on_result=lambda result: store_execution_result(
            request.config,
            request.node.nodeid,
            result,
        ),
    )


@pytest.fixture
def agent_scenario(request: pytest.FixtureRequest) -> ScenarioResultRecorder:
    """Attach execution/verifier data to the current report scenario."""
    return ScenarioResultRecorder(request.config, request.node.nodeid)


@pytest_asyncio.fixture
async def agent_cleanup() -> AsyncIterator[CleanupManager]:
    manager = CleanupManager()
    try:
        yield manager
    finally:
        await manager.run_all()


@pytest.fixture
def agent_execution_result(request: pytest.FixtureRequest) -> AgentExecutionResult | None:
    return request.config.stash[_STASH_KEY].results.get(request.node.nodeid)


def _record_scenario_from_reports(
    state: PluginState,
    item: pytest.Item,
    reports: dict[str, pytest.TestReport],
) -> None:
    writer = state.json_writer
    if writer is None:
        return

    duration_ms = int(sum(report.duration for report in reports.values()) * 1000)
    markers = [marker.name for marker in item.iter_markers()]
    stored_result = state.results.get(item.nodeid)
    skipped = any(report.skipped for report in reports.values())
    failed_reports = [report for report in reports.values() if report.failed]
    call_report = reports.get("call")
    passed = not skipped and not failed_reports and call_report is not None and call_report.passed
    status: ScenarioStatus
    if skipped:
        status = "skipped"
    elif any(report.failed for phase, report in reports.items() if phase != "call"):
        status = "error"
    elif failed_reports:
        status = "failed"
    else:
        status = "passed"
    extra: dict[str, Any] = {}
    if stored_result is not None:
        extra["run_id"] = stored_result.run_id
        extra["tool_calls"] = stored_result.tool_calls

    error_messages = [str(report.longrepr) for report in failed_reports]
    writer.record_scenario(
        name=item.name,
        nodeid=item.nodeid,
        passed=passed,
        skipped=skipped,
        status=status,
        duration_ms=duration_ms,
        markers=markers,
        error_message="; ".join(error_messages) if error_messages else None,
        extra=extra,
        execution_result=stored_result,
        verification_results=state.verification_results.get(item.nodeid, []),
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    outcome = yield
    report = outcome.get_result()

    state = item.config.stash.get(_STASH_KEY, None)
    if state is None:
        return

    phase_reports = state.phase_reports.setdefault(item.nodeid, {})
    phase_reports[report.when] = report
    if report.when == "teardown":
        _record_scenario_from_reports(state, item, phase_reports)
        state.phase_reports.pop(item.nodeid, None)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    state = session.config.stash.get(_STASH_KEY, None)
    if state is None or state.json_writer is None:
        return
    report = state.json_writer.build_report()
    if state.write_json:
        state.json_writer.write(report)
    if state.html_path is not None:
        HtmlReportWriter(state.html_path).write(report)


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


def attach_verification_results(
    config: pytest.Config,
    nodeid: str,
    results: VerificationSummary | Sequence[VerificationResult],
) -> None:
    """Attach side-effect verification results to a report scenario."""
    state = config.stash.get(_STASH_KEY, None)
    if state is None:
        return
    values = list(results.results if isinstance(results, VerificationSummary) else results)
    state.verification_results.setdefault(nodeid, []).extend(values)
