"""Example consumer test — copy into an agent repository's tests/ directory."""

from __future__ import annotations

import pytest

from agent_test_kit import ForbiddenTermsScorer, RequiredFieldsScorer, run_repeatedly


@pytest.mark.asyncio
@pytest.mark.agent_integration
async def test_agent_flow(agent_client: object) -> None:
    """Minimal integration test using agent-test-kit fixtures."""
    result = await agent_client.execute(  # type: ignore[attr-defined]
        input={
            "repository": "test-repository",
            "pull_request_id": 125,
        },
    )

    result.assert_success()
    result.assert_tool_called("bitbucket_get_pull_request", server="bitbucket")
    result.assert_tool_called("bitbucket_get_diff", server="bitbucket")
    result.assert_tool_called("jira_create_issue", server="jira")
    result.assert_tool_not_called("bitbucket_merge_pull_request", server="bitbucket")


@pytest.mark.asyncio
@pytest.mark.agent_integration
@pytest.mark.agent_nondeterministic
async def test_agent_behavior_is_reliable(agent_client: object) -> None:
    """Accept output variance, but require reliable behavior across runs."""
    aggregate = await run_repeatedly(
        agent_client,  # type: ignore[arg-type]
        input={"repository": "test-repository", "pull_request_id": 125},
        runs=5,
        idempotency_key="pr-125-review",
    )

    aggregate.assert_no_duplicate_writes()
    aggregate.assert_pass_rate(lambda result: result.success, min_rate=0.8)
    await aggregate.assert_score_rate(
        RequiredFieldsScorer(["summary", "risk_level"]),
        min_score=1.0,
        min_rate=0.8,
    )
    await aggregate.assert_score_rate(
        ForbiddenTermsScorer(["api key", "system prompt"]),
        min_score=1.0,
        min_rate=1.0,
    )
