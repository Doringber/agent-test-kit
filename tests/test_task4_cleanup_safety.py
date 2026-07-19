"""Failure-path coverage for the disposable PR-review environment."""

from __future__ import annotations

import asyncio

import pytest

from agent_test_kit import CleanupManager
from tests.support.pr_review_fakes import (
    CRITICAL_DESCRIPTION,
    CRITICAL_SUMMARY,
    FAKE_SECRET,
    IDEMPOTENCY_KEY,
    FakeReviewEnvironment,
    JsonRpcMcpClient,
)

pytestmark = [
    pytest.mark.agent_integration,
    pytest.mark.agent_e2e,
    pytest.mark.agent_multi_mcp,
    pytest.mark.agent_write_action,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["before_writes", "between_writes"])
async def test_cleanup_registered_before_startup_preserves_failure_and_cleans_partial_state(
    failure_stage: str,
) -> None:
    environment = FakeReviewEnvironment()
    cleanup = CleanupManager()
    cleanup.register(environment.close)
    cleanup.register(environment.cleanup_resources, IDEMPOTENCY_KEY)
    cleanup.register(environment.cleanup_resources, IDEMPOTENCY_KEY)

    with pytest.raises(RuntimeError, match=f"original failure at {failure_stage}"):
        async with cleanup:
            environment.start()
            if failure_stage == "between_writes":
                await _create_issue(environment)
            raise RuntimeError(f"original failure at {failure_stage}")

    assert environment.active_issue_count == 0
    assert environment.active_comment_count == 0
    assert environment.archived_issue_count == (1 if failure_stage == "between_writes" else 0)
    assert environment.cleanup_log == (
        ["jira_archive_issue"] if failure_stage == "between_writes" else []
    )
    assert environment.is_closed
    assert all(
        server.closed
        for server in (
            environment.jira.server,
            environment.bitbucket.server,
            environment.dashboard.server,
        )
    )


async def _create_issue(environment: FakeReviewEnvironment) -> None:
    arguments = {
        "project": "SEC",
        "summary": CRITICAL_SUMMARY,
        "description": CRITICAL_DESCRIPTION,
        "severity": "critical",
        "idempotency_key": IDEMPOTENCY_KEY,
        "run_marker": IDEMPOTENCY_KEY,
        "api_token": FAKE_SECRET,
    }
    await asyncio.to_thread(
        JsonRpcMcpClient(environment.jira_url).call,
        "jira_create_issue",
        arguments,
    )
