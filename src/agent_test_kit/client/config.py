"""Agent test configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_test_kit.models.enums import ToolOperationKind


class AgentTestConfig(BaseSettings):
    """Configuration for agent test execution."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_TEST_",
        env_file=".env",
        extra="ignore",
    )

    base_url: str = Field(default="http://localhost:8080", description="Agent API base URL")
    execute_path: str = Field(default="/api/v1/execute", description="Agent execute endpoint")
    output_format: str = Field(
        default="stream-json",
        description="Cursor CLI output format when using /agent",
    )
    tool_server_mappings: dict[str, str] = Field(default_factory=dict)
    tool_operation_mappings: dict[str, ToolOperationKind] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=120.0, ge=1.0)
    agent_id: str = Field(default="unknown-agent")
    agent_version: str | None = None
    environment: str = Field(default="local")
    model: str | None = None
    prompt_version: str | None = None
    knowledge_version: str | None = Field(
        default=None,
        description="Version of the RAG index or knowledge base the agent answered from",
    )
    repository: str | None = None
    branch: str | None = None
    commit: str | None = None
    pipeline_id: str | None = None
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")

    @property
    def execute_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.execute_path}"
