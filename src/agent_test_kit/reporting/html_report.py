"""Self-contained, dependency-free HTML report output."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from agent_test_kit.models.report import AgentTestRunReport
from agent_test_kit.reporting.redaction import redact_value


class _TrustedHtml(str):
    """HTML produced internally after validating and escaping all inputs."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, _TrustedHtml):
        return value
    if isinstance(value, (dict, list)):
        return escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return escape(str(value))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td><pre>{_text(cell)}</pre></td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _flow_kind_class(kind: str | None) -> str:
    normalized = (kind or "unknown").lower()
    if normalized == "read":
        return "flow-read"
    if normalized == "write":
        return "flow-write"
    return "flow-unknown"


def _flow_status_class(status: str | None) -> str:
    normalized = (status or "").lower()
    if normalized in {"success", "completed", "ok"}:
        return "flow-ok"
    if normalized in {"error", "failed", "failure", "timeout", "timed_out"}:
        return "flow-bad"
    return "flow-pending"


def _flow_label(server: Any, name: str) -> str:
    server_text = str(server).strip() if server else ""
    if server_text:
        return f"{server_text}/{name}"
    return name


def _flow_sequence(tool_calls: list[dict[str, Any]]) -> str:
    """Render a compact left-to-right tool/MCP data-flow strip."""
    if not tool_calls:
        return '<p class="flow-empty">No tool calls recorded for this scenario.</p>'

    steps: list[str] = []
    for index, tool in enumerate(tool_calls):
        kind = str(tool.get("operation_kind") or "unknown")
        status = str(tool.get("status") or "")
        label = _flow_label(tool.get("server"), str(tool.get("name") or "unknown"))
        step = (
            f'<span class="flow-step {_flow_status_class(status)}">'
            f'<span class="flow-badge {_flow_kind_class(kind)}">{escape(kind.upper())}</span>'
            f"<span class=\"flow-name\">{escape(label)}</span>"
            f"</span>"
        )
        steps.append(step)
        if index < len(tool_calls) - 1:
            steps.append('<span class="flow-arrow" aria-hidden="true">→</span>')
    return f'<div class="flow-strip" role="list">{"".join(steps)}</div>'


class HtmlReportWriter:
    """Render an escaped and redacted report as one portable HTML file."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    def write(self, report: AgentTestRunReport) -> Path:
        payload = redact_value(report.model_dump(mode="json"))
        scenarios = payload["scenarios"]
        scenario_sections = "".join(self._scenario(scenario) for scenario in scenarios)
        metrics = payload["metrics"]
        metadata = [
            ["Agent", payload["agent_id"]],
            ["Agent version", payload.get("agent_version")],
            ["Model", payload.get("model")],
            ["Prompt version", payload.get("prompt_version")],
            ["Environment", payload["environment"]],
            ["Repository", payload.get("repository")],
            ["Branch / commit", f"{payload.get('branch') or ''} {payload.get('commit') or ''}"],
            ["Run", payload["run_id"]],
            ["Started", payload["started_at"]],
            ["Completed", payload["completed_at"]],
        ]
        metric_rows = [[key.replace("_", " ").title(), value] for key, value in metrics.items()]
        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent test report</title>
<style>
body{{font:14px system-ui,sans-serif;margin:2rem;color:#18212f;background:#f5f7fa}}
main{{max-width:1200px;margin:auto}}h1,h2,h3{{margin:.6em 0}}
.card{{background:white;border:1px solid #d8dee8;border-radius:8px;padding:1rem;margin:1rem 0}}
.status{{font-weight:700;text-transform:uppercase}}.passed{{color:#16794b}}
.failed,.error{{color:#b42318}}.skipped{{color:#805b10}}
table{{border-collapse:collapse;width:100%;margin:.75rem 0}}
th,td{{border:1px solid #d8dee8;padding:.5rem;text-align:left;vertical-align:top}}
th{{background:#edf1f7}}
pre{{white-space:pre-wrap;word-break:break-word;margin:0;font:12px ui-monospace}}
details{{margin:.6rem 0}}a{{color:#175cd3}}
.flow-strip{{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .5rem;margin:.75rem 0;padding:.75rem;background:#f8fafc;border:1px solid #d8dee8;border-radius:8px}}
.flow-step{{display:inline-flex;align-items:center;gap:.35rem;padding:.25rem .45rem;border-radius:6px;border:1px solid #d0d7e2;background:#fff}}
.flow-step.flow-ok{{border-color:#86bfa3}}.flow-step.flow-bad{{border-color:#e08a8a;background:#fff5f5}}
.flow-step.flow-pending{{border-color:#c9b26a;background:#fffbeb}}
.flow-badge{{font:10px/1 ui-monospace;font-weight:700;padding:.15rem .35rem;border-radius:4px;color:#fff}}
.flow-badge.flow-read{{background:#175cd3}}.flow-badge.flow-write{{background:#b42318}}
.flow-badge.flow-unknown{{background:#667085}}
.flow-name{{font:12px ui-monospace;font-weight:600;color:#18212f}}
.flow-arrow{{color:#667085;font-weight:700;padding:0 .1rem}}
.flow-empty{{color:#667085;font-style:italic;margin:.5rem 0}}
</style>
</head>
<body><main>
<h1>Agent test report</h1>
<section class="card"><h2>Metadata</h2>{_table(["Field", "Value"], metadata)}</section>
<section class="card"><h2>Run metrics</h2>{_table(["Metric", "Value"], metric_rows)}</section>
<h2>Scenarios</h2>{scenario_sections}
</main></body></html>"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(document, encoding="utf-8")
        return self.output_path

    def _scenario(self, scenario: dict[str, Any]) -> str:
        status = str(scenario["status"])
        tool_rows = [
            [
                tool.get("server"),
                tool["name"],
                tool["status"],
                tool.get("attempt"),
                tool.get("arguments"),
                tool.get("output"),
            ]
            for tool in scenario["tool_calls"]
        ]
        assertion_rows = [
            [
                assertion["name"],
                assertion["passed"],
                assertion.get("expected"),
                assertion.get("actual"),
                assertion.get("message"),
            ]
            for assertion in scenario["assertions"]
        ]
        verification_rows = [
            [
                verification["verifier_name"],
                verification["passed"],
                verification.get("message"),
                self._links(verification.get("evidence_links", [])),
                verification.get("evidence"),
            ]
            for verification in scenario["side_effect_verifications"]
        ]
        timeline_rows = [
            [
                event["timestamp"],
                event["event_type"],
                event["label"],
                event.get("server"),
                event.get("tool_name"),
                event.get("status"),
                event.get("metadata"),
            ]
            for event in scenario["timeline"]
        ]
        summary = [
            ["Node", scenario["nodeid"]],
            ["Duration (ms)", scenario["duration_ms"]],
            ["Run", scenario.get("run_id")],
            ["Markers", scenario["markers"]],
            ["Retries", scenario["retry_count"]],
            ["Tokens", scenario.get("token_usage")],
            ["Estimated cost (USD)", scenario.get("estimated_cost_usd")],
            ["Error", scenario.get("error_message")],
        ]
        verification_table = _table(
            ["Verifier", "Passed", "Message", "Evidence links", "Evidence"],
            verification_rows,
        )
        flow_html = _flow_sequence(scenario["tool_calls"])
        return f"""<section class="card">
<h3>{_text(scenario["name"])} — <span class="status {escape(status)}">{escape(status)}</span></h3>
{_table(["Field", "Value"], summary)}
<h4>Tool flow</h4>
{flow_html}
<details open><summary>Assertions ({len(assertion_rows)})</summary>
{_table(["Name", "Passed", "Expected", "Actual", "Message"], assertion_rows)}</details>
<details><summary>Side effects ({len(verification_rows)})</summary>
{verification_table}</details>
<details><summary>Tool / MCP calls ({len(tool_rows)})</summary>
{_table(["Server", "Tool", "Status", "Attempt", "Arguments", "Output"], tool_rows)}</details>
<details><summary>Timeline ({len(timeline_rows)})</summary>
{_table(["Time", "Type", "Label", "Server", "Tool", "Status", "Metadata"], timeline_rows)}</details>
</section>"""

    @staticmethod
    def _links(links: list[str]) -> _TrustedHtml:
        return _TrustedHtml(
            " ".join(
                f'<a href="{escape(link, quote=True)}">{escape(link)}</a>'
                for link in links
                if link.startswith(("https://", "http://"))
            )
        )
