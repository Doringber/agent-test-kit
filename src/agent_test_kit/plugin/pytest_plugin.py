"""Pytest plugin for agent-test-kit."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from agent_test_kit.cleanup.manager import CleanupManager
from agent_test_kit.client.agent_client import AgentClient
from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.client.cursor_agent_client import CursorAgentClient
from agent_test_kit.client.prompt_ai_helper_profiles import get_profile
from agent_test_kit.evals.base import Eval, EvalReport, get_eval
from agent_test_kit.guardrails.base import (
    Guardrail,
    GuardrailMonitor,
    GuardrailReport,
    check_guardrails,
)
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.report import AgentTestRunReport, ReleaseReadiness, ScenarioStatus
from agent_test_kit.reporting.html_report import HtmlReportWriter
from agent_test_kit.reporting.json_report import JsonReportWriter
from agent_test_kit.reporting.readiness import ReadinessPolicy, evaluate_readiness, load_report
from agent_test_kit.verifiers import (
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
    VerificationSummary,
    run_verifiers,
)

if TYPE_CHECKING:
    from agent_test_kit.regression import RegressionRunEvaluation


@dataclass
class PluginState:
    agent_config: AgentTestConfig
    json_writer: JsonReportWriter | None
    results: dict[str, AgentExecutionResult] = field(default_factory=dict)
    verification_results: dict[str, list[VerificationResult]] = field(default_factory=dict)
    regression_evaluations: dict[str, RegressionRunEvaluation] = field(default_factory=dict)
    guardrail_checks: dict[str, list[Any]] = field(default_factory=dict)
    eval_checks: dict[str, list[Any]] = field(default_factory=dict)
    phase_reports: dict[str, dict[str, pytest.TestReport]] = field(default_factory=dict)
    html_path: Path | None = None
    write_json: bool = True
    baseline_path: Path | None = None
    readiness_policy: ReadinessPolicy = field(default_factory=ReadinessPolicy)
    enforce_readiness: bool = False


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
    baseline_path = config.getoption("--agent-baseline", default=None)
    config.stash[_STASH_KEY] = PluginState(
        agent_config=agent_config,
        json_writer=writer,
        html_path=Path(html_path) if html_path else None,
        write_json=bool(json_path),
        baseline_path=Path(baseline_path) if baseline_path else None,
        readiness_policy=ReadinessPolicy(
            min_persona_pass_rate=config.getoption("--agent-min-persona-pass-rate", default=None)
        ),
        enforce_readiness=bool(config.getoption("--agent-enforce-readiness", default=False)),
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

    def attach_regression_evaluation(self, evaluation: RegressionRunEvaluation) -> None:
        """Record goal, persona, and pass rate for readiness segmentation."""
        state = self.config.stash.get(_STASH_KEY, None)
        if state is not None:
            state.regression_evaluations[self.nodeid] = evaluation

    def attach_guardrail_report(self, report: GuardrailReport) -> None:
        """Record guardrail checks on the current scenario."""
        attach_guardrail_report(self.config, self.nodeid, report)

    def attach_eval_report(self, report: EvalReport) -> None:
        """Record eval scores on the current scenario."""
        attach_eval_report(self.config, self.nodeid, report)

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


@dataclass
class _GuardrailFixture:
    """Run guardrails for the current test and attach them to the report."""

    config: pytest.Config
    nodeid: str
    monitors: list[GuardrailMonitor] = field(default_factory=list)
    _closed: bool = False

    def check(
        self,
        result: AgentExecutionResult,
        guardrails: Guardrail | Sequence[Guardrail],
        *,
        fail: bool = True,
    ) -> GuardrailReport:
        """Run guardrails offline. Failures are recorded even when the assertion fails."""
        report = check_guardrails(result, guardrails)
        result.guardrail_checks.extend(report.checks)
        attach_guardrail_report(self.config, self.nodeid, report)
        if fail:
            report.assert_passed()
        return report

    def monitor(
        self,
        guardrails: Guardrail | Sequence[Guardrail],
        *,
        fail_fast: bool = False,
    ) -> GuardrailMonitor:
        """Online hook. Trace rules run when the monitor or this fixture finishes."""
        monitor = GuardrailMonitor(guardrails, fail_fast=fail_fast)
        self.monitors.append(monitor)
        return monitor

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for monitor in self.monitors:
            if not monitor.finished:
                monitor.finish(notify=False, raise_on_violation=False)
            if monitor.last_report is not None:
                attach_guardrail_report(self.config, self.nodeid, monitor.last_report)


@dataclass
class _EvalFixture:
    """Run registered or explicit evals for the current test."""

    config: pytest.Config
    nodeid: str
    names: list[str]

    def run(
        self,
        result: AgentExecutionResult,
        evals: Eval | Sequence[Eval] | None = None,
        *,
        fail: bool = True,
    ) -> EvalReport:
        """Score evals. Marker names are used when ``evals`` is omitted."""
        from agent_test_kit.evals.base import run_evals

        selected: Eval | Sequence[Eval]
        if evals is None:
            if not self.names:
                raise RuntimeError(
                    "No evals to run. Pass evals=[...] or mark the test with "
                    "@pytest.mark.agent_eval('registered_name')."
                )
            selected = [get_eval(name) for name in self.names]
        else:
            selected = evals
        report = run_evals(result, selected)
        result.eval_checks.extend(report.results)
        attach_eval_report(self.config, self.nodeid, report)
        if fail:
            report.assert_passed()
        return report


@pytest.fixture
def agent_guardrails(request: pytest.FixtureRequest) -> Iterator[_GuardrailFixture]:
    """Offline ``check`` and online ``monitor`` for guardrails on this test."""
    runner = _GuardrailFixture(request.config, request.node.nodeid)
    yield runner
    runner.close()


@pytest.fixture
def agent_eval(request: pytest.FixtureRequest) -> _EvalFixture:
    """Run evals named by ``@pytest.mark.agent_eval`` or passed to ``run``."""
    return _EvalFixture(
        request.config,
        request.node.nodeid,
        _agent_eval_names(request.node),
    )


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
        regression_evaluation=state.regression_evaluations.get(item.nodeid),
        guardrail_checks=state.guardrail_checks.get(item.nodeid, []),
        eval_checks=state.eval_checks.get(item.nodeid, []),
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
    report.readiness = _evaluate_session_readiness(state, report)
    if state.write_json:
        state.json_writer.write(report)
    if state.html_path is not None:
        HtmlReportWriter(state.html_path).write(report)
    if (
        state.enforce_readiness
        and report.readiness.verdict == "no_go"
        and exitstatus == pytest.ExitCode.OK
    ):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _evaluate_session_readiness(
    state: PluginState,
    report: AgentTestRunReport,
) -> ReleaseReadiness:
    baseline: AgentTestRunReport | None = None
    notes: list[str] = []
    if state.baseline_path is not None:
        try:
            baseline = load_report(state.baseline_path)
        except FileNotFoundError:
            notes.append(f"Baseline report not found: {state.baseline_path}")
        except (OSError, ValueError) as exc:
            path, reason = state.baseline_path, type(exc).__name__
            notes.append(f"Baseline report unreadable: {path} ({reason})")
    return evaluate_readiness(
        report,
        baseline=baseline,
        policy=state.readiness_policy,
        notes=notes,
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


def _agent_eval_names(node: pytest.Item | pytest.Collector) -> list[str]:
    names: list[str] = []
    for marker in node.iter_markers("agent_eval"):
        for arg in marker.args:
            if not isinstance(arg, str) or not arg.strip():
                raise ValueError("agent_eval marker arguments must be non-empty eval names")
            names.append(arg)
    return names


def attach_guardrail_report(
    config: pytest.Config,
    nodeid: str,
    report: GuardrailReport,
) -> None:
    """Attach guardrail checks to a report scenario."""
    state = config.stash.get(_STASH_KEY, None)
    if state is None:
        return
    bucket = state.guardrail_checks.setdefault(nodeid, [])
    for check in report.checks:
        if check not in bucket:
            bucket.append(check)


def attach_eval_report(
    config: pytest.Config,
    nodeid: str,
    report: EvalReport,
) -> None:
    """Attach eval results to a report scenario."""
    state = config.stash.get(_STASH_KEY, None)
    if state is None:
        return
    bucket = state.eval_checks.setdefault(nodeid, [])
    for result in report.results:
        if result not in bucket:
            bucket.append(result)


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
