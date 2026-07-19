"""Task 3 publisher and Markdown status output tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from agent_test_kit.models.report import AgentTestRunReport
from agent_test_kit.publishing import (
    HttpResultPublisher,
    ResultPublisherConfig,
    ResultPublishError,
)
from agent_test_kit.reporting.markdown_status import MarkdownStatusReportWriter


def _report() -> AgentTestRunReport:
    now = datetime.now(UTC)
    return AgentTestRunReport(
        run_id="run_publish",
        agent_id="agent",
        environment="test",
        started_at=now,
        completed_at=now,
        repository="repo",
    )


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    ("url", "token"),
    [
        ("http://dashboard.example/results", None),
        ("http://dashboard.example/results", "secret"),
        ("ftp://dashboard.example/results", None),
    ],
)
def test_result_publisher_config_rejects_insecure_non_loopback_urls(
    url: str,
    token: str | None,
) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        ResultPublisherConfig(url=url, token=token)


@pytest.mark.agent_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/results",
        "http://127.0.0.1:8080/results",
        "http://[::1]:8080/results",
    ],
)
async def test_http_result_publisher_allows_token_bearing_loopback_http(url: str) -> None:
    publisher = HttpResultPublisher(
        ResultPublisherConfig(url=url, token="local-secret"),
        transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"accepted": True})),
    )

    result = await publisher.publish(_report())

    assert result.success


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_http_result_publisher_posts_redacted_report_and_token_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHBOARD_TEST_TOKEN", "super-secret")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(202, json={"accepted": True})

    publisher = HttpResultPublisher(
        ResultPublisherConfig(
            url="https://dashboard.example/results",
            token_env="DASHBOARD_TEST_TOKEN",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await publisher.publish(_report())

    assert result.success is True
    assert result.status_code == 202
    assert captured["authorization"] == "Bearer super-secret"
    assert captured["payload"]["run_id"] == "run_publish"  # type: ignore[index]
    assert "super-secret" not in repr(result)


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_http_result_publisher_normalizes_errors_and_optional_pipeline_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="dashboard unavailable")

    transport = httpx.MockTransport(handler)
    soft = HttpResultPublisher(
        ResultPublisherConfig(url="https://dashboard.example/results"),
        transport=transport,
    )
    soft_result = await soft.publish(_report())
    assert soft_result.success is False
    assert soft_result.status_code == 503
    assert soft_result.error == "Dashboard returned HTTP 503"

    strict = HttpResultPublisher(
        ResultPublisherConfig(
            url="https://dashboard.example/results",
            fail_pipeline_on_publish_error=True,
        ),
        transport=transport,
    )
    with pytest.raises(ResultPublishError, match="HTTP 503"):
        await strict.publish(_report())


@pytest.mark.agent_unit
def test_markdown_status_writer_records_operational_provenance(tmp_path: Path) -> None:
    writer = MarkdownStatusReportWriter(tmp_path / "status.md", title="Task 3 validation")
    writer.record_provenance("agent-test-kit", "0.1.1")
    writer.record_command("pytest --cov", exit_code=0)
    writer.set_counts(passed=10, failed=0, skipped=1, errors=0)
    writer.add_artifact("JSON report", "reports/result.json")
    writer.add_evidence("Jira issue", "https://jira.example/ABC-1")
    writer.add_cleanup("temporary issue", "deleted")
    writer.add_skip("live dashboard unavailable")
    writer.add_blocker("production credentials intentionally absent")

    output = writer.write()
    markdown = output.read_text(encoding="utf-8")

    assert "agent-test-kit `0.1.1`" in markdown
    assert "`pytest --cov` — exit 0" in markdown
    assert "Passed: 10" in markdown
    assert "[Jira issue](https://jira.example/ABC-1)" in markdown
    assert "temporary issue — deleted" in markdown
    assert "live dashboard unavailable" in markdown
    assert "production credentials intentionally absent" in markdown
