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
        return f"""<section class="card">
<h3>{_text(scenario["name"])} — <span class="status {escape(status)}">{escape(status)}</span></h3>
{_table(["Field", "Value"], summary)}
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
