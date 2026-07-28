"""Deterministic multi-MCP PR-review acceptance demonstration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_test_kit import (
    AgentClient,
    AgentTestConfig,
    CleanupManager,
    HtmlReportWriter,
    HttpResultPublisher,
    JsonReportWriter,
    ResultPublisherConfig,
    ToolStep,
    VerificationContext,
    run_repeatedly,
    run_verifiers,
)
from agent_test_kit.models.enums import ToolCallStatus
from tests.support.pr_review_fakes import (
    CRITICAL_DESCRIPTION,
    CRITICAL_SUMMARY,
    FAKE_SECRET,
    IDEMPOTENCY_KEY,
    PR_REVIEW_REQUEST,
    FakeReviewEnvironment,
    ReviewStateVerifier,
)

pytestmark = [
    pytest.mark.agent_integration,
    pytest.mark.agent_e2e,
    pytest.mark.agent_multi_mcp,
    pytest.mark.agent_write_action,
]


@pytest.mark.asyncio
async def test_deterministic_pr_review_acceptance_flow(tmp_path: Path) -> None:
    """Exercise the public package API over real local HTTP boundaries."""
    environment = FakeReviewEnvironment()
    json_path = tmp_path / "pr-review-report.json"
    html_path = tmp_path / "pr-review-report.html"

    cleanup = CleanupManager()
    cleanup.register(environment.close)
    cleanup.register(environment.cleanup_resources, IDEMPOTENCY_KEY)

    with pytest.raises(AssertionError, match="forced acceptance assertion failure"):
        async with cleanup:
            environment.start()
            client = AgentClient(
                AgentTestConfig(
                    base_url=environment.agent_url,
                    agent_id="deterministic-pr-review-agent",
                    environment="acceptance",
                    repository="payments-api",
                    model="deterministic-rules-v1",
                    timeout_seconds=5,
                )
            )
            repeated = await run_repeatedly(
                client,
                input=PR_REVIEW_REQUEST,
                runs=2,
                idempotency_key=IDEMPOTENCY_KEY,
            )

            repeated.assert_stable_success()
            repeated.assert_responses_stable()
            repeated.assert_no_duplicate_writes()
            assert {context.idempotency_key for context in repeated.contexts} == {IDEMPOTENCY_KEY}

            first, second = repeated.results
            expected_pr_arguments = {
                "workspace": "acme_dev",
                "repository": "payments-api",
                "pull_request_id": 42,
                "run_marker": IDEMPOTENCY_KEY,
            }
            expected_diff_arguments = {
                **expected_pr_arguments,
                "context_lines": 3,
            }
            expected_jira_arguments = {
                "project": "SEC",
                "summary": CRITICAL_SUMMARY,
                "description": CRITICAL_DESCRIPTION,
                "severity": "critical",
                "idempotency_key": IDEMPOTENCY_KEY,
                "run_marker": IDEMPOTENCY_KEY,
                "api_token": FAKE_SECRET,
            }
            expected_comment_arguments = {
                **expected_pr_arguments,
                "content": (
                    "Blocked: critical SQL injection at src/payments.py:18. "
                    "Tracking issue SEC-1001."
                ),
                "idempotency_key": IDEMPOTENCY_KEY,
            }

            first.assert_success()
            first.assert_tool_sequence(
                [
                    ToolStep(
                        "bitbucket",
                        "bitbucket_get_pullrequest_by_id",
                        status=ToolCallStatus.SUCCESS,
                        arguments=expected_pr_arguments,
                    ),
                    ToolStep(
                        "bitbucket",
                        "bitbucket_get_pr_diff",
                        status=ToolCallStatus.SUCCESS,
                        arguments=expected_diff_arguments,
                    ),
                    ToolStep(
                        "jira",
                        "jira_create_issue",
                        status=ToolCallStatus.SUCCESS,
                        arguments=expected_jira_arguments,
                    ),
                    ToolStep(
                        "bitbucket",
                        "bitbucket_post_pr_comment",
                        status=ToolCallStatus.SUCCESS,
                        arguments=expected_comment_arguments,
                    ),
                ],
                status=ToolCallStatus.SUCCESS,
            )
            assert [call.arguments for call in first.tool_calls] == [
                expected_pr_arguments,
                expected_diff_arguments,
                expected_jira_arguments,
                expected_comment_arguments,
            ]
            first.assert_read_before_write(
                read_tool=("bitbucket", "bitbucket_get_pr_diff"),
                write_tool=("jira", "jira_create_issue"),
            )
            first.assert_write_tool_called_once(server="jira", tool="jira_create_issue")
            first.assert_write_tool_called_once(
                server="bitbucket",
                tool="bitbucket_post_pr_comment",
            )
            first.assert_tool_not_called("bitbucket_merge_pullrequest", server="bitbucket")
            first.assert_no_failed_tool_calls()
            first.assert_max_workflow_steps(4)
            first.assert_max_retries(0)

            second.assert_success()
            second.assert_tool_not_called("jira_create_issue", server="jira")
            second.assert_tool_not_called("bitbucket_post_pr_comment", server="bitbucket")
            second.assert_tool_not_called("bitbucket_merge_pullrequest", server="bitbucket")
            second.assert_no_failed_tool_calls()
            second.assert_max_workflow_steps(4)
            second.assert_max_retries(0)

            write_log = environment.write_call_log
            assert [entry["tool"] for entry in write_log] == [
                "jira_create_issue",
                "bitbucket_post_pr_comment",
            ]
            assert all(
                entry["arguments"]["idempotency_key"] == IDEMPOTENCY_KEY for entry in write_log
            )
            assert environment.active_issue_count == 1
            assert environment.active_comment_count == 1
            assert environment.merge_count == 0

            verifier = ReviewStateVerifier(
                jira_url=environment.jira_url,
                bitbucket_url=environment.bitbucket_url,
                idempotency_key=IDEMPOTENCY_KEY,
            )
            verification = await run_verifiers(
                [verifier],
                VerificationContext(
                    run_id=first.run_id,
                    correlation_id=first.correlation_id,
                    execution_result=first,
                    metadata={"request": PR_REVIEW_REQUEST},
                ),
                timeout_seconds=2,
            )
            assert verification.passed
            assert verification.results[0].message == (
                "One Jira issue and one PR comment exist; pull request was not merged"
            )
            assert len(verification.evidence_links) == 2

            report_writer = JsonReportWriter(
                config=client.config,
                output_path=json_path,
            )
            report_writer.record_scenario(
                name="deterministic critical PR review",
                nodeid=(
                    "tests/test_task4_pr_review_acceptance.py::"
                    "test_deterministic_pr_review_acceptance_flow"
                ),
                passed=True,
                duration_ms=1,
                markers=[
                    "agent_integration",
                    "agent_e2e",
                    "agent_multi_mcp",
                    "agent_write_action",
                ],
                execution_result=first,
                verification_results=verification.results,
            )
            report = report_writer.build_report()
            report_writer.write(report)
            HtmlReportWriter(html_path).write(report)

            json_text = json_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
            report_payload = json.loads(json_text)
            assert FAKE_SECRET not in json_text
            assert FAKE_SECRET not in html_text
            assert "[REDACTED]" in json_text
            assert "<style>" in html_text
            assert "<script src=" not in html_text
            assert "<link rel=" not in html_text
            assert report_payload["metrics"]["passed"] == 1
            assert report_payload["metrics"]["total_tool_calls"] == 4
            scenario = report_payload["scenarios"][0]
            assert scenario["markers"] == [
                "agent_integration",
                "agent_e2e",
                "agent_multi_mcp",
                "agent_write_action",
            ]
            assert scenario["assertions"]
            assert scenario["side_effect_verifications"][0]["passed"] is True
            assert len(scenario["side_effect_verifications"][0]["evidence_links"]) == 2

            publish_result = await HttpResultPublisher(
                ResultPublisherConfig(
                    url=f"{environment.dashboard_url}/ingest",
                    token="dashboard-test-token",
                    timeout_seconds=2,
                )
            ).publish(report)
            assert publish_result.success
            assert publish_result.status_code == 202
            assert environment.dashboard_payload == report_payload
            assert environment.dashboard_authorization == "Bearer dashboard-test-token"
            assert FAKE_SECRET not in json.dumps(environment.dashboard_payload)

            raise AssertionError("forced acceptance assertion failure")

    assert environment.active_issue_count == 0
    assert environment.active_comment_count == 0
    assert environment.archived_issue_count == 1
    assert environment.closed_comment_count == 1
    assert environment.cleanup_log == [
        "jira_archive_issue",
        "bitbucket_close_pr_comment",
    ]
    assert environment.mcp_request_ledger == [
        {
            "sequence": 1,
            "server": "bitbucket",
            "tool": "bitbucket_get_pullrequest_by_id",
            "arguments": expected_pr_arguments,
        },
        {
            "sequence": 2,
            "server": "bitbucket",
            "tool": "bitbucket_get_pr_diff",
            "arguments": expected_diff_arguments,
        },
        {
            "sequence": 3,
            "server": "jira",
            "tool": "jira_create_issue",
            "arguments": expected_jira_arguments,
        },
        {
            "sequence": 4,
            "server": "bitbucket",
            "tool": "bitbucket_post_pr_comment",
            "arguments": expected_comment_arguments,
        },
        {
            "sequence": 5,
            "server": "bitbucket",
            "tool": "bitbucket_get_pullrequest_by_id",
            "arguments": expected_pr_arguments,
        },
        {
            "sequence": 6,
            "server": "bitbucket",
            "tool": "bitbucket_get_pr_diff",
            "arguments": expected_diff_arguments,
        },
        {
            "sequence": 7,
            "server": "jira",
            "tool": "jira_search_issues",
            "arguments": {"project": "SEC", "run_marker": IDEMPOTENCY_KEY},
        },
        {
            "sequence": 8,
            "server": "bitbucket",
            "tool": "bitbucket_get_pr_review_state",
            "arguments": expected_pr_arguments,
        },
        {
            "sequence": 9,
            "server": "jira",
            "tool": "jira_search_issues",
            "arguments": {"project": "SEC", "run_marker": IDEMPOTENCY_KEY},
        },
        {
            "sequence": 10,
            "server": "bitbucket",
            "tool": "bitbucket_get_pr_review_state",
            "arguments": expected_pr_arguments,
        },
        {
            "sequence": 11,
            "server": "jira",
            "tool": "jira_archive_issue",
            "arguments": {
                "issue_key": "SEC-1001",
                "idempotency_key": IDEMPOTENCY_KEY,
            },
        },
        {
            "sequence": 12,
            "server": "bitbucket",
            "tool": "bitbucket_close_pr_comment",
            "arguments": {
                "comment_id": 7001,
                "idempotency_key": IDEMPOTENCY_KEY,
            },
        },
    ]
    assert environment.is_closed
    assert json_path.is_file()
    assert html_path.is_file()
