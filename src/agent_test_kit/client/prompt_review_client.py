"""HTTP client for prompt-ai-helper /prompt/review and /prompt/health."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from agent_test_kit.client.prompt_ai_helper_profiles import PromptAiHelperProfile
from agent_test_kit.models.execution import AgentExecutionResult, utc_now
from agent_test_kit.models.trace import AgentTrace, TraceEvent


class PromptReviewClient:
    """Call prompt-ai-helper review pipeline (Cursor hook target)."""

    def __init__(
        self,
        profile: PromptAiHelperProfile,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.profile = profile
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)
        self._verify = profile.verify_ssl

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            verify=self._verify,
        ) as client:
            response = await client.get(self.profile.health_url)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                msg = "Health response must be a JSON object"
                raise ValueError(msg)
            return body

    async def review(
        self,
        prompt: str,
        *,
        repo_slug: str | None = None,
        model: str | None = None,
        user_email: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AgentExecutionResult:
        """POST /prompt/review and normalize to AgentExecutionResult for reporting."""
        started_at = utc_now()
        run_id = f"review_{uuid.uuid4().hex[:12]}"
        payload: dict[str, Any] = {"prompt": prompt}
        if repo_slug is not None:
            payload["repo_slug"] = repo_slug
        if model is not None:
            payload["model"] = model
        elif self.profile.model:
            payload["model"] = self.profile.model
        if user_email is not None:
            payload["user_email"] = user_email
        if extra:
            payload.update(extra)

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                verify=self._verify,
            ) as client:
                response = await client.post(
                    self.profile.review_url,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            return AgentExecutionResult(
                success=False,
                run_id=run_id,
                error=f"Prompt review timed out: {exc}",
                started_at=started_at,
            )
        except httpx.TransportError as exc:
            return AgentExecutionResult(
                success=False,
                run_id=run_id,
                error=f"Transport failure: {exc}",
                started_at=started_at,
            )

        duration_ms = int((time.perf_counter() - t0) * 1000)
        if response.is_error:
            return AgentExecutionResult(
                success=False,
                run_id=run_id,
                error=f"HTTP {response.status_code}: {response.text[:500]}",
                response={"status_code": response.status_code},
                started_at=started_at,
            )

        body = response.json()
        if not isinstance(body, dict):
            return AgentExecutionResult(
                success=False,
                run_id=run_id,
                error="Review response must be a JSON object",
                started_at=started_at,
            )

        suggested = body.get("suggested_prompt") or body.get("suggestedPrompt")
        reason = str(body.get("reason") or "")
        success = bool(suggested) or body.get("continue") is True or body.get("action") == "allow"

        return AgentExecutionResult(
            success=success,
            run_id=run_id,
            response={
                **body,
                "original_prompt": prompt,
                "scenario_kind": "prompt_review",
                "endpoint_base_url": self.profile.base_url,
                "profile": self.profile.name,
                "duration_ms": duration_ms,
            },
            error=None if success else (reason or "Review returned no suggestion"),
            trace=AgentTrace(
                events=[
                    TraceEvent(
                        timestamp=started_at,
                        label="prompt_review_submitted",
                        event_type="prompt_review",
                        metadata={"repo_slug": repo_slug, "model": payload.get("model")},
                    ),
                    TraceEvent(
                        timestamp=utc_now(),
                        label="prompt_review_completed",
                        event_type="prompt_review",
                        status="success" if success else "error",
                        metadata={"reason": reason, "source": body.get("source")},
                    ),
                ],
            ),
            started_at=started_at,
        )
