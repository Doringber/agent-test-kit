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
        return '<p class="flow-empty">No MCP tool calls recorded for this scenario.</p>'

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


def _metric_cards(metrics: dict[str, Any]) -> str:
    cards = [
        ("Scenarios", metrics.get("total_scenarios"), "metric-neutral"),
        ("Passed", metrics.get("passed"), "metric-pass"),
        ("Failed", metrics.get("failed"), "metric-fail"),
        ("Tool calls", metrics.get("total_tool_calls"), "metric-neutral"),
        ("Tokens", metrics.get("total_token_usage") or "—", "metric-neutral"),
        ("Est. cost", metrics.get("estimated_cost_usd") or "—", "metric-neutral"),
    ]
    body = "".join(
        f'<div class="metric-card {css}"><div class="metric-value">{escape(str(val))}</div>'
        f'<div class="metric-label">{escape(label)}</div></div>'
        for label, val, css in cards
    )
    return f'<div class="metric-grid">{body}</div>'


def _endpoint_table(endpoints: dict[str, str]) -> str:
    if not endpoints:
        return ""
    rows = [[name, url] for name, url in endpoints.items()]
    return (
        '<section class="card endpoint-card"><h2>Service endpoints</h2>'
        + _table(["Endpoint", "URL"], rows)
        + "</section>"
    )


def _mcp_server_chips(servers: list[str], expected: list[str] | None = None) -> str:
    if not servers and not expected:
        return '<p class="flow-empty">No connected MCP servers recorded.</p>'
    expected_set = set(expected or [])
    chips: list[str] = []
    for server in servers:
        css = "mcp-chip connected"
        if expected_set and server in expected_set:
            css = "mcp-chip connected expected"
        chips.append(f'<span class="{css}">{escape(server)}</span>')
    for server in expected or []:
        if server not in servers:
            chips.append(f'<span class="mcp-chip missing">{escape(server)} (expected)</span>')
    return f'<div class="mcp-chips">{"".join(chips)}</div>'


def _prompt_review_block(scenario: dict[str, Any]) -> str:
    original = scenario.get("original_prompt")
    suggested = scenario.get("suggested_prompt")
    if not original and not suggested:
        return ""
    return f"""<div class="prompt-review">
<h4>Prompt review pipeline</h4>
<div class="prompt-cols">
<div class="prompt-pane"><div class="prompt-label">Original prompt</div><pre>{_text(original)}</pre></div>
<div class="prompt-pane suggested"><div class="prompt-label">Suggested prompt</div><pre>{_text(suggested)}</pre></div>
</div></div>"""


def _golden_outcome_block(scenario: dict[str, Any]) -> str:
    golden = scenario.get("golden_outcome")
    violation_types = scenario.get("violation_types") or []
    expected_class = scenario.get("expected_classification")
    golden_met = scenario.get("golden_met")
    if not golden and not violation_types:
        return ""
    chips = "".join(
        f'<span class="violation-chip">{escape(str(v))}</span>' for v in violation_types
    )
    met = ""
    if golden_met is not None:
        css = "golden-met" if golden_met else "golden-miss"
        label = "GOLDEN MET" if golden_met else "GOLDEN MISS"
        met = f'<span class="golden-flag {css}">{label}</span>'
    class_badge = ""
    if expected_class:
        class_badge = f'<span class="classification-chip">{escape(str(expected_class))}</span>'
    return f"""<div class="golden-outcome">
<h4>Golden expected outcome</h4>
<div class="golden-meta">{class_badge}{met}</div>
<p>{_text(golden)}</p>
<div class="violation-chips">{chips}</div>
</div>"""


def _bullet_list(items: list[Any]) -> str:
    return "<ul>" + "".join(f"<li>{_text(item)}</li>" for item in items) + "</ul>"


def _readiness_block(readiness: dict[str, Any] | None) -> str:
    if not readiness:
        return ""
    go = readiness.get("verdict") == "go"
    css = "readiness-go" if go else "readiness-no-go"
    label = "GO" if go else "NO-GO"
    parts = [
        f'<section class="card readiness {css}">'
        f'<h2>Release readiness <span class="verdict">{label}</span></h2>'
        '<p class="readiness-hint">Evidence for a human release decision.</p>'
    ]
    blocking = readiness.get("blocking") or []
    if blocking:
        parts.append(f"<h4>Blocking</h4>{_bullet_list(blocking)}")
    notes = readiness.get("notes") or []
    if notes:
        parts.append(f"<h4>Notes</h4>{_bullet_list(notes)}")
    segments = readiness.get("persona_segments") or []
    if segments:
        rows = [
            [
                segment["persona"],
                segment["scenarios"],
                segment["passed"],
                f"{segment['pass_rate']:.0%}",
            ]
            for segment in segments
        ]
        parts.append(
            "<h4>Personas</h4>" + _table(["Persona", "Scenarios", "Passed", "Pass rate"], rows)
        )
    baseline = readiness.get("baseline")
    if baseline:
        rows = [
            [change, values]
            for change, values in (
                ("Regressions", baseline.get("regressions")),
                ("Pass-rate drops", baseline.get("pass_rate_drops")),
                ("Not run", baseline.get("missing_scenarios")),
                ("Fingerprint changes", baseline.get("fingerprint_changes")),
            )
            if values
        ]
        body = _table(["Change", "Details"], rows) if rows else "<p>No changes.</p>"
        parts.append(f"<h4>Baseline {_text(baseline.get('baseline_run_id'))}</h4>{body}")
    parts.append("</section>")
    return "".join(parts)


def _behavior_rows(scenario: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    if scenario.get("case_id"):
        rows.append(["Case", scenario["case_id"]])
    if scenario.get("goal"):
        rows.append(["Goal", scenario["goal"]])
    if scenario.get("persona"):
        rows.append(["Persona", scenario["persona"]])
    if scenario.get("pass_rate") is not None:
        required = scenario.get("min_pass_rate")
        suffix = f" (required {required:.0%})" if required is not None else ""
        rows.append(["Pass rate", f"{scenario['pass_rate']:.0%}{suffix}"])
    if scenario.get("run_count") is not None:
        rows.append(["Runs", scenario["run_count"]])
    return rows


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
            ["Knowledge version", payload.get("knowledge_version")],
            ["Environment", payload["environment"]],
            ["Repository", payload.get("repository")],
            ["Branch / commit", f"{payload.get('branch') or ''} {payload.get('commit') or ''}"],
            ["Run", payload["run_id"]],
            ["Started", payload["started_at"]],
            ["Completed", payload["completed_at"]],
        ]
        metric_rows = [[key.replace("_", " ").title(), value] for key, value in metrics.items()]
        env_badge = escape(str(payload.get("environment") or "local"))
        agent_badge = escape(str(payload.get("agent_id") or "agent"))
        endpoint_html = _endpoint_table(payload.get("endpoint_profile") or {})
        expected_mcp = payload.get("expected_mcp_servers") or []
        global_mcp = _mcp_server_chips(
            sorted(
                {
                    server
                    for scenario in scenarios
                    for server in (scenario.get("connected_mcp_servers") or [])
                }
            ),
            expected_mcp if isinstance(expected_mcp, list) else [],
        )
        mcp_overview = (
            f'<section class="card"><h2>Connected MCP servers (run)</h2>{global_mcp}</section>'
            if global_mcp
            else ""
        )
        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent test report — {agent_badge}</title>
<style>
:root{{--bg:#eef2f7;--card:#fff;--line:#d8dee8;--text:#18212f;--muted:#667085;--pass:#16794b;--fail:#b42318;--accent:#175cd3}}
*{{box-sizing:border-box}}body{{font:14px/1.5 system-ui,sans-serif;margin:0;color:var(--text);background:var(--bg)}}
main{{max-width:1280px;margin:0 auto;padding:1.5rem 1rem 3rem}}
.hero{{background:linear-gradient(135deg,#1e3a5f,#175cd3);color:#fff;border-radius:12px;padding:1.25rem 1.5rem;margin-bottom:1rem}}
.hero h1{{margin:0 0 .35rem;font-size:1.5rem}}.hero-meta{{opacity:.9;font-size:.9rem}}
.badges{{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.75rem}}
.badge{{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);padding:.2rem .55rem;border-radius:999px;font-size:.75rem;font-weight:600}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem 1.1rem;margin:1rem 0;box-shadow:0 1px 2px rgba(16,24,40,.04)}}
.endpoint-card table td:first-child{{font-weight:600;white-space:nowrap;width:12rem}}
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.75rem;margin:1rem 0}}
.metric-card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.85rem;text-align:center}}
.metric-value{{font-size:1.35rem;font-weight:700}}.metric-label{{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;margin-top:.15rem}}
.metric-pass .metric-value{{color:var(--pass)}}.metric-fail .metric-value{{color:var(--fail)}}
h2,h3,h4{{margin:.5em 0}}.scenario-card{{border-left:4px solid var(--line)}}
.scenario-card.passed{{border-left-color:var(--pass)}}.scenario-card.failed,.scenario-card.error{{border-left-color:var(--fail)}}
.scenario-card.skipped{{border-left-color:#b8860b}}
.status{{font-weight:700;text-transform:uppercase}}.passed{{color:var(--pass)}}.failed,.error{{color:var(--fail)}}.skipped{{color:#805b10}}
table{{border-collapse:collapse;width:100%;margin:.75rem 0}}th,td{{border:1px solid var(--line);padding:.5rem;text-align:left;vertical-align:top}}th{{background:#edf1f7}}
pre{{white-space:pre-wrap;word-break:break-word;margin:0;font:12px ui-monospace}}
details{{margin:.6rem 0}}a{{color:var(--accent)}}
.flow-strip{{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .5rem;margin:.75rem 0;padding:.75rem;background:#f8fafc;border:1px solid var(--line);border-radius:8px}}
.flow-step{{display:inline-flex;align-items:center;gap:.35rem;padding:.25rem .45rem;border-radius:6px;border:1px solid #d0d7e2;background:#fff}}
.flow-step.flow-ok{{border-color:#86bfa3}}.flow-step.flow-bad{{border-color:#e08a8a;background:#fff5f5}}
.flow-step.flow-pending{{border-color:#c9b26a;background:#fffbeb}}
.flow-badge{{font:10px/1 ui-monospace;font-weight:700;padding:.15rem .35rem;border-radius:4px;color:#fff}}
.flow-badge.flow-read{{background:var(--accent)}}.flow-badge.flow-write{{background:var(--fail)}}
.flow-badge.flow-unknown{{background:var(--muted)}}
.flow-name{{font:12px ui-monospace;font-weight:600;color:var(--text)}}
.flow-arrow{{color:var(--muted);font-weight:700;padding:0 .1rem}}.flow-empty{{color:var(--muted);font-style:italic;margin:.5rem 0}}
.prompt-review{{margin:.75rem 0}}.prompt-cols{{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}}
@media(max-width:800px){{.prompt-cols{{grid-template-columns:1fr}}}}
.prompt-pane{{border:1px solid var(--line);border-radius:8px;padding:.65rem;background:#fafbfc}}
.prompt-pane.suggested{{border-color:#86bfa3;background:#f6fffa}}
.prompt-label{{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:.35rem;font-weight:700}}
.scenario-kind{{display:inline-block;background:#eef4ff;color:var(--accent);font-size:.7rem;font-weight:700;padding:.15rem .45rem;border-radius:4px;margin-left:.5rem;text-transform:uppercase}}
.mcp-chips{{display:flex;flex-wrap:wrap;gap:.4rem;margin:.5rem 0 .75rem}}
.mcp-chip{{font:11px ui-monospace;font-weight:700;padding:.25rem .55rem;border-radius:999px;border:1px solid var(--line);background:#fff}}
.mcp-chip.connected{{background:#eef4ff;border-color:#b2c9ff;color:var(--accent)}}
.mcp-chip.expected{{background:#ecfdf3;border-color:#86bfa3;color:var(--pass)}}
.mcp-chip.missing{{background:#fff5f5;border-color:#e08a8a;color:var(--fail)}}
.injection-flag{{display:inline-block;margin-left:.5rem;padding:.15rem .45rem;border-radius:4px;font-size:.7rem;font-weight:700}}
.injection-flag.detected{{background:#fff5f5;color:var(--fail)}}
.injection-flag.safe{{background:#ecfdf3;color:var(--pass)}}
.golden-outcome{{margin:.75rem 0;padding:.75rem;border:1px solid var(--line);border-radius:8px;background:#fafbfc}}
.golden-meta{{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.4rem}}
.golden-flag{{font-size:.7rem;font-weight:700;padding:.15rem .45rem;border-radius:4px}}
.golden-flag.golden-met{{background:#ecfdf3;color:var(--pass)}}
.golden-flag.golden-miss{{background:#fff5f5;color:var(--fail)}}
.classification-chip{{font-size:.7rem;font-weight:700;padding:.15rem .45rem;border-radius:4px;background:#eef4ff;color:var(--accent)}}
.violation-chips{{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.4rem}}
.violation-chip{{font:10px ui-monospace;padding:.15rem .4rem;border-radius:4px;background:#f2f4f7;color:var(--muted)}}
.readiness{{border-left:6px solid var(--line)}}
.readiness-go{{border-left-color:var(--pass)}}.readiness-no-go{{border-left-color:var(--fail)}}
.verdict{{font-size:.85rem;font-weight:800;padding:.2rem .6rem;border-radius:6px;color:#fff}}
.verdict{{margin-left:.5rem;vertical-align:middle}}
.readiness-go .verdict{{background:var(--pass)}}.readiness-no-go .verdict{{background:var(--fail)}}
.readiness-hint{{color:var(--muted);margin:.2rem 0 .5rem}}
</style>
</head>
<body><main>
<header class="hero">
<h1>Agent test report</h1>
<div class="hero-meta">Framework {escape(str(payload.get("framework_version") or ""))} · Run {escape(str(payload["run_id"]))}</div>
<div class="badges"><span class="badge">Agent: {agent_badge}</span><span class="badge">Env: {env_badge}</span></div>
</header>
{_readiness_block(payload.get("readiness"))}
{_metric_cards(metrics)}
{endpoint_html}
{mcp_overview}
<section class="card"><h2>Run metadata</h2>{_table(["Field", "Value"], metadata)}</section>
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
            *_behavior_rows(scenario),
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
        kind = scenario.get("scenario_kind")
        kind_badge = (
            f'<span class="scenario-kind">{escape(str(kind))}</span>' if kind else ""
        )
        prompt_review_html = _prompt_review_block(scenario)
        golden_html = _golden_outcome_block(scenario)
        connected = scenario.get("connected_mcp_servers") or []
        expected_mcp = scenario.get("expected_mcp_servers") or []
        mcp_html = _mcp_server_chips(
            connected if isinstance(connected, list) else [],
            expected_mcp if isinstance(expected_mcp, list) else [],
        )
        injection = scenario.get("injection_detected")
        injection_html = ""
        if injection is not None:
            css = "detected" if injection else "safe"
            label = "INJECTION MITIGATED" if injection else "NO INJECTION FLAG"
            injection_html = f'<span class="injection-flag {css}">{label}</span>'
        status_class = escape(status)
        return f"""<section class="card scenario-card {status_class}">
<h3>{_text(scenario["name"])}{kind_badge}{injection_html} — <span class="status {status_class}">{escape(status)}</span></h3>
{_table(["Field", "Value"], summary)}
<h4>Connected MCP servers</h4>
{mcp_html}
{golden_html}
{prompt_review_html}
<h4>MCP tool flow</h4>
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
