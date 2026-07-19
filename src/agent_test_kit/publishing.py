"""Redacted agent report publishing contracts and HTTP implementation."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from pydantic import AliasChoices, BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_test_kit.models.report import AgentTestRunReport
from agent_test_kit.reporting.redaction import redact_value

_HTTP_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ResultPublisherConfig(BaseSettings):
    """Dashboard publisher settings loaded from AGENT_TEST_DASHBOARD_*."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_TEST_DASHBOARD_URL", "url"),
    )
    token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_TEST_DASHBOARD_TOKEN", "token"),
    )
    token_env: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AGENT_TEST_DASHBOARD_TOKEN_ENV",
            "token_env",
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias=AliasChoices(
            "AGENT_TEST_DASHBOARD_TIMEOUT_SECONDS",
            "timeout_seconds",
        ),
    )
    fail_pipeline_on_publish_error: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AGENT_TEST_DASHBOARD_FAIL_PIPELINE_ON_PUBLISH_ERROR",
            "fail_pipeline_on_publish_error",
        ),
    )

    @model_validator(mode="after")
    def require_secure_dashboard_url(self) -> ResultPublisherConfig:
        """Require TLS except for explicit loopback test endpoints."""
        if self.url is None:
            return self
        try:
            parsed = urlsplit(self.url)
            host = parsed.hostname
        except ValueError as exc:
            raise ValueError("Dashboard URL must be a valid HTTPS URL") from exc
        if parsed.scheme == "https" and host:
            return self
        if parsed.scheme == "http" and host and host.lower() in _HTTP_LOOPBACK_HOSTS:
            return self
        raise ValueError(
            "Dashboard URL must use HTTPS; HTTP is allowed only for "
            "localhost, 127.0.0.1, or ::1 test endpoints"
        )

    def resolved_token(self) -> str | None:
        """Resolve an indirect token first, then the standard TOKEN setting."""
        if self.token_env:
            return os.getenv(self.token_env)
        return self.token.get_secret_value() if self.token is not None else None


class PublishResult(BaseModel):
    """Normalized result that is safe to log."""

    model_config = {"extra": "forbid"}

    success: bool
    status_code: int | None = None
    error: str | None = None


class ResultPublishError(RuntimeError):
    """Raised when publishing fails and pipeline failure is configured."""


@runtime_checkable
class ResultPublisher(Protocol):
    """Consumer-pluggable report destination."""

    async def publish(self, report: AgentTestRunReport) -> PublishResult:
        """Publish a completed report."""
        ...


class HttpResultPublisher:
    """POST redacted reports to an HTTP dashboard endpoint."""

    def __init__(
        self,
        config: ResultPublisherConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or ResultPublisherConfig()
        self._transport = transport

    async def publish(self, report: AgentTestRunReport) -> PublishResult:
        if not self.config.url:
            return self._failure("Dashboard URL is not configured")
        token = self.config.resolved_token()
        if self.config.token_env and not token:
            return self._failure(
                f"Dashboard token environment variable {self.config.token_env!r} is not set"
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = redact_value(report.model_dump(mode="json"))
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self.config.url,
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            return self._failure(f"Dashboard transport error ({exc.__class__.__name__})")
        if not response.is_success:
            return self._failure(
                f"Dashboard returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return PublishResult(success=True, status_code=response.status_code)

    def _failure(self, message: str, *, status_code: int | None = None) -> PublishResult:
        if self.config.fail_pipeline_on_publish_error:
            raise ResultPublishError(message)
        return PublishResult(success=False, status_code=status_code, error=message)
