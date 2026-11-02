"""Guardrail and eval results render in the JSON and HTML reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_test_kit import (
    AgentExecutionResult,
    AgentTestConfig,
    HtmlReportWriter,
    JsonReportWriter,
    NoProfanityGuardrail,
    RequiredTermsEval,
    ToolCall,
    guardrail,
    must_open_pull_request,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.trace import AgentTrace
from agent_test_kit.plugin import pytest_plugin

pytestmark = pytest.mark.agent_unit


def _result() -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="run_report",
        response="What the fuck — I opened the pull request.",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="github",
                    name="create_pull_request",
                    status=ToolCallStatus.SUCCESS,
                    operation_kind=ToolOperationKind.WRITE,
                )
            ]
        ),
    )


def test_html_report_includes_guardrail_and_eval_sections(tmp_path: Path) -> None:
    result = _result()
    with pytest.raises(AssertionError):
        result.assert_guardrails([NoProfanityGuardrail(), must_open_pull_request(server="github")])
    with pytest.raises(AssertionError):
        result.assert_evals(RequiredTermsEval(["refund"], name="mentions_refund"))

    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="report-agent"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="guardrails and evals",
        nodeid="tests/test_report.py::test_guardrails",
        passed=False,
        status="failed",
        duration_ms=5,
        markers=["agent_unit"],
        execution_result=result,
    )
    report = writer.build_report()
    scenario = report.scenarios[0]
    assert [item.name for item in scenario.guardrails] == [
        "no_profanity",
        "must_open_pull_request",
    ]
    assert scenario.guardrails[0].passed is False
    assert scenario.guardrails[0].mode == "offline"
    assert scenario.guardrails[1].passed is True
    assert scenario.evals[0].name == "mentions_refund"
    assert scenario.evals[0].passed is False
    assert scenario.evals[0].score == 0.0

    html = HtmlReportWriter(tmp_path / "report.html").write(report).read_text(encoding="utf-8")
    assert "Guardrails (2)" in html
    assert "Evals (1)" in html
    assert "no_profanity" in html
    assert "must_open_pull_request" in html
    assert "mentions_refund" in html
    assert "Disallowed language" in html
    assert "offline" in html


def test_report_escapes_guardrail_messages_and_dedupes_checks(tmp_path: Path) -> None:
    @guardrail(phase="message", name="markup")
    def markup(text: str) -> str:
        return "<script>alert(1)</script>"

    result = AgentExecutionResult(success=True, run_id="run_html", response="hello")
    with pytest.raises(AssertionError):
        result.assert_guardrails(markup)
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="report-agent"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="<scenario>",
        nodeid="tests/demo.py::test_demo",
        passed=False,
        duration_ms=1,
        markers=[],
        execution_result=result,
        guardrail_checks=list(result.guardrail_checks),
    )
    scenario = writer.build_report().scenarios[0]
    assert len(scenario.guardrails) == 1
    html = (
        HtmlReportWriter(tmp_path / "report.html")
        .write(writer.build_report())
        .read_text(encoding="utf-8")
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_plugin_records_guardrails_and_evals_from_fixture_state(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    result = AgentExecutionResult(success=True, run_id="run_plugin", response="hello refund")
    evaluation = result.assert_evals(RequiredTermsEval(["refund"]))
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="demo"),
        output_path=tmp_path / "report.json",
    )
    state = pytest_plugin.PluginState(
        agent_config=AgentTestConfig(),
        json_writer=writer,
        results={"tests/demo.py::test_demo": result},
        eval_checks={"tests/demo.py::test_demo": list(evaluation.results)},
    )
    item = MagicMock()
    item.nodeid = "tests/demo.py::test_demo"
    item.name = "test_demo"
    item.iter_markers.return_value = []
    reports: dict[str, MagicMock] = {}
    for phase in ("setup", "call", "teardown"):
        report = MagicMock()
        report.when = phase
        report.duration = 0.01
        report.skipped = False
        report.failed = False
        report.passed = True
        report.longrepr = None
        reports[phase] = report
    pytest_plugin._record_scenario_from_reports(state, item, reports)
    scenario = writer.scenarios[0]
    assert len(scenario.evals) == 1
    assert scenario.evals[0].passed is True
    assert scenario.evals[0].score == 1.0
    payload = json.loads(writer.write().read_text(encoding="utf-8"))
    assert payload["scenarios"][0]["evals"][0]["name"] == "required_terms"


def test_html_omits_guardrail_and_eval_sections_when_absent(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="empty"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="plain",
        nodeid="tests/plain.py::test_plain",
        passed=True,
        duration_ms=1,
        markers=[],
    )
    html = (
        HtmlReportWriter(tmp_path / "report.html")
        .write(writer.build_report())
        .read_text(encoding="utf-8")
    )
    assert "Guardrails (" not in html
    assert "Evals (" not in html


def test_pytest_session_html_includes_guardrails_and_evals(
    pytester: pytest.Pytester,
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "report.html"
    pytester.makepyfile(
        """
import pytest

from agent_test_kit import (
    AgentExecutionResult,
    NoProfanityGuardrail,
    RequiredTermsEval,
    ToolCall,
    must_open_pull_request,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.trace import AgentTrace


@pytest.mark.agent_unit
def test_recorded_run(agent_guardrails, agent_eval):
    result = AgentExecutionResult(
        success=True,
        run_id="run_1",
        response="I opened the pull request.",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="github",
                    name="create_pull_request",
                    status=ToolCallStatus.SUCCESS,
                    operation_kind=ToolOperationKind.WRITE,
                )
            ]
        ),
    )
    agent_guardrails.check(
        result,
        [NoProfanityGuardrail(), must_open_pull_request(server="github")],
    )
    agent_eval.run(result, [RequiredTermsEval(["pull request"])])
"""
    )
    result = pytester.runpytest(f"--agent-report-html={html_path}", "-q")
    result.assert_outcomes(passed=1)
    html = html_path.read_text(encoding="utf-8")
    assert "Guardrails (2)" in html
    assert "no_profanity" in html
    assert "must_open_pull_request" in html
    assert "Evals (1)" in html
    assert "required_terms" in html
    assert "pull request" in html or "1.00" in html
