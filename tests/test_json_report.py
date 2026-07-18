"""JSON report writer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.reporting.json_report import JsonReportWriter


@pytest.mark.agent_unit
def test_json_report_writer(tmp_path: Path) -> None:
    config = AgentTestConfig(agent_id="demo-agent", environment="test")
    output = tmp_path / "agent-results.json"
    writer = JsonReportWriter(config=config, output_path=output)
    writer.record_scenario(
        name="test_flow",
        nodeid="tests/test_flow.py::test_flow",
        passed=True,
        duration_ms=120,
        markers=["agent_integration"],
    )
    path = writer.write()
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["agent_id"] == "demo-agent"
    assert payload["metrics"]["total_scenarios"] == 1
    assert payload["metrics"]["passed"] == 1
