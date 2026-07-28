"""prompt-ai-helper integration: review pipeline, real MCP tools, injection dataset."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from agent_test_kit import (
    AgentTestConfig,
    CursorAgentClient,
    PromptReviewClient,
    get_profile,
)
from tests.support.prompt_injection_dataset import (
    evaluate_injection_review,
    load_prompt_injection_cases,
)

pytestmark = [pytest.mark.agent_integration]


def _require_live() -> None:
    if os.getenv("ENABLE_REAL_AGENT_TEST", "").strip() != "1":
        pytest.skip("Set ENABLE_REAL_AGENT_TEST=1 for live prompt-ai-helper tests")


def _profile_name() -> str:
    return os.getenv("PROMPT_AI_HELPER_ENV", "integration").strip().lower()


def _cursor_client(profile_name: str | None = None) -> CursorAgentClient:
    profile = get_profile(profile_name or _profile_name())
    return CursorAgentClient(
        AgentTestConfig(
            base_url=profile.base_url,
            execute_path=profile.agent_path,
            output_format="stream-json",
            agent_id="prompt-ai-helper",
            environment=profile.name,
            model=profile.model,
            timeout_seconds=180.0,
            verify_ssl=profile.verify_ssl,
            tool_server_mappings={
                "echo": profile.mcp_servers[0] if profile.mcp_servers else "unknown",
                "get_mcp_tools": "cursor-meta",
            },
        )
    )


REVIEW_CASES: list[dict[str, str]] = [
    {
        "id": "vague_prompt",
        "prompt": "test",
        "repo_slug": "agent-test-kit",
        "expect_in_suggestion": "Acceptance criteria",
    },
    {
        "id": "atlassian_read",
        "prompt": (
            "READ-ONLY: Use atlassian-platform MCP to search Jira for one open issue "
            "in project QA. No writes. Summarize in 3 bullets."
        ),
        "repo_slug": "my-agent",
        "expect_in_suggestion": "READ",
    },
    {
        "id": "coralogix_logs",
        "prompt": (
            "READ-ONLY: Use coralogix MCP get_datetime tool, then describe how you would "
            "fetch recent error logs for qa-helper. No writes."
        ),
        "repo_slug": "my-agent",
        "expect_in_suggestion": "coralogix",
    },
]


MCP_TOOL_CASES: list[dict[str, Any]] = [
    {
        "id": "atlassian_echo",
        "server": "atlassian-platform",
        "tool": "echo",
        "prompt": (
            "READ-ONLY MCP TEST: Call atlassian-platform MCP echo tool exactly once "
            'with message "agent-test-kit-atlassian-echo". Return the echo response JSON.'
        ),
        "forbidden_tools": [],
    },
    {
        "id": "coralogix_get_datetime",
        "server": "coralogix",
        "tool": "get_datetime",
        "prompt": (
            "READ-ONLY MCP TEST: Call coralogix MCP get_datetime tool exactly once. "
            "Return the tool output only."
        ),
        "forbidden_tools": [],
    },
]


class _MockReviewTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "service": "prompt-ai-helper"})
        body = json.loads(request.content.decode())
        prompt = body.get("prompt", "")
        return httpx.Response(
            200,
            json={
                "suggested_prompt": f"Improved: {prompt}\n\n## Acceptance criteria\n- [ ] done",
                "source": "mock",
                "reason": "mock review",
            },
        )


@pytest.mark.agent_unit
@pytest.mark.parametrize("case", REVIEW_CASES, ids=[c["id"] for c in REVIEW_CASES])
@pytest.mark.asyncio
async def test_prompt_review_mock(case: dict[str, str], agent_scenario) -> None:
    profile = get_profile("integration")
    client = PromptReviewClient(profile, transport=_MockReviewTransport(), timeout_seconds=5)
    result = await client.review(case["prompt"], repo_slug=case["repo_slug"])
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    suggested = str(result.response.get("suggested_prompt", ""))
    assert case["expect_in_suggestion"].lower() in suggested.lower()


@pytest.mark.agent_e2e
@pytest.mark.parametrize("case", REVIEW_CASES, ids=[c["id"] for c in REVIEW_CASES])
@pytest.mark.asyncio
async def test_prompt_review_live(case: dict[str, str], agent_scenario) -> None:
    _require_live()
    profile = get_profile(_profile_name())
    client = PromptReviewClient(profile, timeout_seconds=120.0)
    result = await client.review(case["prompt"], repo_slug=case["repo_slug"])
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    suggested = str(result.response.get("suggested_prompt", ""))
    assert len(suggested) > len(case["prompt"])
    assert case["expect_in_suggestion"].lower() in suggested.lower()


@pytest.mark.agent_e2e
@pytest.mark.agent_security
@pytest.mark.parametrize(
    "case",
    load_prompt_injection_cases(),
    ids=[c.id for c in load_prompt_injection_cases()],
)
@pytest.mark.asyncio
async def test_prompt_injection_review_live(case, agent_scenario) -> None:
    """Inject golden guard prompts into /prompt/review and score against golden_outcome."""
    _require_live()
    profile = get_profile(_profile_name())
    client = PromptReviewClient(profile, timeout_seconds=120.0)
    result = await client.review(case.prompt, repo_slug="agent-test-kit")
    suggested = str(result.response.get("suggested_prompt") or "")
    evaluation = evaluate_injection_review(
        case,
        original=case.prompt,
        suggested=suggested,
    )
    result.response["injection_detected"] = evaluation["injection_detected"]
    result.response["injection_evaluation"] = evaluation
    result.response["violation_types"] = case.violation_types
    result.response["golden_outcome"] = case.golden_outcome
    result.response["expected_classification"] = case.expected_classification
    result.response["golden_met"] = evaluation["golden_met"]
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    assert evaluation["mutated"], f"Review did not mutate injection case {case.id}"
    # injection_detected + leaked_patterns appear in HTML report for manual review.
    if case.category == "control":
        assert "read" in suggested.lower()


@pytest.mark.agent_e2e
@pytest.mark.parametrize("case", MCP_TOOL_CASES, ids=[c["id"] for c in MCP_TOOL_CASES])
@pytest.mark.asyncio
async def test_real_mcp_tool_call_live(case: dict[str, Any], agent_scenario) -> None:
    """Live /agent must call tools on connected MCP servers (not just mention them)."""
    _require_live()
    profile = get_profile(_profile_name())
    cursor = _cursor_client()
    result = await cursor.execute_prompt(
        str(case["prompt"]),
        mode="agent",
        timeout_seconds=180.0,
    )
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    connected = result.trace.connected_mcp_servers
    assert case["server"] in connected, (
        f"Expected connected MCP {case['server']}, got {connected}"
    )
    result.assert_tool_called(case["tool"], server=case["server"])
    for forbidden in case.get("forbidden_tools", []):
        result.assert_tool_not_called(forbidden)


@pytest.mark.agent_e2e
@pytest.mark.asyncio
async def test_prompt_ai_helper_health_live(agent_scenario) -> None:
    _require_live()
    profile = get_profile(_profile_name())
    client = PromptReviewClient(profile, timeout_seconds=30.0)
    health: dict[str, Any] = await client.health()
    assert health.get("status") == "ok"
    assert "prompt-ai-helper" in str(health.get("service", ""))


@pytest.mark.agent_e2e
@pytest.mark.asyncio
async def test_prompt_ai_helper_agent_ask_sanity_live(agent_scenario) -> None:
    """Live /agent call with Auto model — read-only JSON sanity."""
    _require_live()
    cursor = _cursor_client()
    result = await cursor.execute_prompt(
        'Return JSON only: {"sanity":"ok","service":"prompt-ai-helper"}',
        mode="ask",
        timeout_seconds=120.0,
    )
    agent_scenario.attach_execution_result(result)

    result.assert_success()
    result.assert_read_only()
    profile = get_profile(_profile_name())
    for server in profile.mcp_servers:
        assert server in result.trace.connected_mcp_servers


@pytest.mark.agent_unit
def test_profile_respects_agent_test_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TEST_BASE_URL", "http://127.0.0.1:18081")
    profile = get_profile("integration")
    assert profile.base_url == "http://127.0.0.1:18081"
    monkeypatch.delenv("AGENT_TEST_BASE_URL", raising=False)


@pytest.mark.agent_unit
def test_profile_endpoint_table() -> None:
    profile = get_profile("integration")
    rows = dict(profile.endpoint_rows())
    assert rows["Review API (hook)"].endswith("/prompt/review")
    assert rows["Health"].endswith("/prompt/health")
    assert "atlassian-platform" in profile.mcp_servers


@pytest.mark.agent_unit
def test_injection_dataset_loads() -> None:
    from tests.support.prompt_injection_dataset import dataset_metadata, load_golden_prompt_guard_cases

    meta = dataset_metadata()
    cases = load_golden_prompt_guard_cases()
    assert len(cases) >= 10
    assert meta.get("schema_version") == "2.0"
    assert any(case.category == "adversarial" for case in cases)
    assert any(case.violation_types for case in cases)
