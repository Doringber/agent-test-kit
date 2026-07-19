"""Concurrent, failure-isolated side-effect verifier orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from agent_test_kit.verifiers.protocols import (
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
)


def _evidence_links(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith(("https://", "http://")) else []
    if isinstance(value, dict):
        return [link for item in value.values() for link in _evidence_links(item)]
    if isinstance(value, (list, tuple)):
        return [link for item in value for link in _evidence_links(item)]
    return []


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    """Ordered aggregate returned after all verifiers finish."""

    results: tuple[VerificationResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[VerificationResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def evidence_links(self) -> list[str]:
        return [link for result in self.results for link in _evidence_links(result.evidence)]


async def _run_one(
    verifier: SideEffectVerifier,
    context: VerificationContext,
    timeout_seconds: float,
) -> VerificationResult:
    started = monotonic()
    try:
        result = await asyncio.wait_for(
            verifier.verify(context),
            timeout=timeout_seconds,
        )
        result.verifier_name = verifier.name
        result.duration_ms = int((monotonic() - started) * 1000)
        return result
    except TimeoutError:
        return VerificationResult(
            verifier_name=verifier.name,
            passed=False,
            message=f"Verifier timed out after {timeout_seconds:g} seconds",
            duration_ms=int((monotonic() - started) * 1000),
            error_type="TimeoutError",
            timed_out=True,
        )
    except Exception as exc:  # noqa: BLE001 - verifier failures are report data
        return VerificationResult(
            verifier_name=verifier.name,
            passed=False,
            message=str(exc) or exc.__class__.__name__,
            duration_ms=int((monotonic() - started) * 1000),
            error_type=exc.__class__.__name__,
        )


async def run_verifiers(
    verifiers: list[SideEffectVerifier] | tuple[SideEffectVerifier, ...],
    context: VerificationContext,
    *,
    timeout_seconds: float = 10.0,
) -> VerificationSummary:
    """Run verifiers concurrently while preserving declaration order."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    results = await asyncio.gather(
        *(_run_one(verifier, context, timeout_seconds) for verifier in verifiers)
    )
    return VerificationSummary(tuple(results))
