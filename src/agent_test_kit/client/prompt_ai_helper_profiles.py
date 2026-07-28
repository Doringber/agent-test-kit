"""Known prompt-ai-helper deployment profiles (Auto model agents)."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class PromptAiHelperProfile(BaseModel):
    """Endpoint bundle for a prompt-ai-helper environment."""

    name: str
    base_url: str
    review_path: str = "/prompt/review"
    health_path: str = "/prompt/health"
    agent_path: str = "/agent"
    stream_path: str = "/stream"
    model: str = "auto"
    verify_ssl: bool = False
    mcp_servers: list[str] = Field(default_factory=list)

    @property
    def review_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.review_path}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.health_path}"

    @property
    def agent_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.agent_path}"

    @property
    def stream_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.stream_path}"

    def endpoint_rows(self) -> list[tuple[str, str]]:
        return [
            ("Review API (hook)", self.review_url),
            ("Health", self.health_url),
            ("Agent test", self.agent_url),
            ("Stream (SSE)", self.stream_url),
        ]


PROFILES: dict[str, PromptAiHelperProfile] = {
    "integration": PromptAiHelperProfile(
        name="integration",
        base_url="https://prompt-ai-helper-int.example.com",
        mcp_servers=["atlassian-platform", "coralogix"],
    ),
    "staging": PromptAiHelperProfile(
        name="staging",
        base_url="https://prompt-ai-helper-stg.example.com",
        mcp_servers=["atlassian-platform", "coralogix"],
    ),
    "development": PromptAiHelperProfile(
        name="development",
        base_url="https://prompt-ai-helper-dev.example.com",
        mcp_servers=["atlassian-platform", "coralogix"],
    ),
}


def get_profile(name: str) -> PromptAiHelperProfile:
    key = name.strip().lower()
    if key not in PROFILES:
        allowed = ", ".join(sorted(PROFILES))
        msg = f"Unknown prompt-ai-helper profile {name!r}; choose one of: {allowed}"
        raise KeyError(msg)
    profile = PROFILES[key].model_copy()
    override = os.getenv("AGENT_TEST_BASE_URL", "").strip().rstrip("/")
    if override:
        profile = profile.model_copy(update={"base_url": override})
    return profile
