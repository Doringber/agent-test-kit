"""Task 3 report aggregation and HTML rendering tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.execution import AgentExecutionResult, AssertionOutcome
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace, TraceEvent
from agent_test_kit.reporting.html_report import HtmlReportWriter
from agent_test_kit.reporting.json_report import JsonReportWriter
from agent_test_kit.verifiers import VerificationResult


@pytest.mark.agent_unit
def test_report_aggregates_execution_verification_and_run_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    calls = [
        ToolCall(
            server="jira",
            name="create_issue",
            arguments={"password": "hidden", "summary": "one"},
            output={"url": "https://jira.example/1"},
            status=ToolCallStatus.SUCCESS,
            attempt=3,
            operation_kind=ToolOperationKind.WRITE,
        ),
        ToolCall(
            server="jira",
            name="create_issue",
            arguments={"summary": "two"},
            status=ToolCallStatus.SUCCESS,
            operation_kind=ToolOperationKind.WRITE,
        ),
    ]
    execution = AgentExecutionResult(
        success=True,
        run_id="run_report",
        trace=AgentTrace(
            tool_calls=calls,
            events=[
                TraceEvent(
                    timestamp=now,
                    label="created",
                    event_type="tool_result",
                    tool_name="create_issue",
                )
            ],
            token_usage=30,
            estimated_cost_usd=0.25,
        ),
        assertions=["legacy consumer assertion"],
        assertion_outcomes=[
            AssertionOutcome(
                name="security_policy",
                passed=False,
                expected="safe",
                actual="unsafe",
                message="unsafe content",
            )
        ],
    )
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="report-agent"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="security",
        nodeid="tests/test_security.py::test_security",
        passed=False,
        status="failed",
        duration_ms=25,
        markers=["agent_security"],
        execution_result=execution,
        verification_results=[
            VerificationResult(
                verifier_name="jira",
                passed=True,
                evidence={"url": "https://jira.example/1"},
            )
        ],
    )

    report = writer.build_report()
    scenario = report.scenarios[0]
    assert execution.assertions == ["legacy consumer assertion"]
    assert scenario.status == "failed"
    assert scenario.timeline[0].label == "created"
    assert scenario.assertions[0].expected == "safe"
    assert scenario.side_effect_verifications[0].evidence_links == ["https://jira.example/1"]
    assert scenario.retry_count == 2
    assert report.metrics.total_token_usage == 30
    assert report.metrics.estimated_cost_usd == 0.25
    assert report.metrics.duplicate_write_count == 1
    assert report.metrics.security_failure_count == 1


@pytest.mark.agent_unit
def test_html_report_is_self_contained_escaped_and_redacted(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="<agent>", model="model-x"),
        output_path=tmp_path / "report.json",
    )
    execution = AgentExecutionResult(
        success=False,
        run_id="run_html",
        error="<script>alert(1)</script>",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    name="danger",
                    arguments={"api_key": "secret-value"},
                    output="<unsafe>",
                )
            ]
        ),
    )
    writer.record_scenario(
        name="<scenario>",
        nodeid="tests/demo.py::test_demo",
        passed=False,
        status="error",
        duration_ms=1,
        markers=[],
        error_message=execution.error,
        execution_result=execution,
    )

    output = HtmlReportWriter(tmp_path / "report.html").write(writer.build_report())
    html = output.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "secret-value" not in html
    assert "[REDACTED]" in html
    assert "<style>" in html
    assert "model-x" in html


@pytest.mark.agent_unit
def test_html_report_renders_tool_flow_strip(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="flow-agent"),
        output_path=tmp_path / "report.json",
    )
    execution = AgentExecutionResult(
        success=True,
        run_id="run_flow",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="bitbucket",
                    name="get_pull_request",
                    operation_kind=ToolOperationKind.READ,
                    status=ToolCallStatus.SUCCESS,
                ),
                ToolCall(
                    server="jira",
                    name="create_issue",
                    operation_kind=ToolOperationKind.WRITE,
                    status=ToolCallStatus.SUCCESS,
                ),
            ]
        ),
    )
    writer.record_scenario(
        name="multi-mcp flow",
        nodeid="tests/flow.py::test_flow",
        passed=True,
        duration_ms=10,
        markers=["agent_e2e"],
        execution_result=execution,
    )

    html = HtmlReportWriter(tmp_path / "report.html").write(writer.build_report()).read_text(
        encoding="utf-8"
    )

    assert "flow-strip" in html
    assert "bitbucket/get_pull_request" in html
    assert "jira/create_issue" in html
    assert "flow-read" in html
    assert "flow-write" in html
    assert "flow-arrow" in html


@pytest.mark.agent_unit
def test_html_report_shows_empty_flow_message_without_tool_calls(tmp_path: Path) -> None:
    writer = JsonReportWriter(
        config=AgentTestConfig(agent_id="empty-flow"),
        output_path=tmp_path / "report.json",
    )
    writer.record_scenario(
        name="no tools",
        nodeid="tests/empty.py::test_empty",
        passed=True,
        duration_ms=1,
        markers=[],
    )

    html = HtmlReportWriter(tmp_path / "report.html").write(writer.build_report()).read_text(
        encoding="utf-8"
    )

    assert "flow-empty" in html
    assert "No MCP tool calls recorded" in html
