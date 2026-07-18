"""Example consumer test — copy into an agent repository's tests/ directory."""

from __future__ import annotations

import pytest


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
