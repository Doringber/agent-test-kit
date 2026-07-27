"""JSON report generation for pytest runs."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.models.report import (
    AgentTestRunReport,
    AssertionReport,
    ScenarioReport,
    ScenarioStatus,
    SideEffectVerificationReport,
    count_duplicate_writes,
)
from agent_test_kit.reporting.redaction import redact_value
from agent_test_kit.verifiers.protocols import VerificationResult


def _evidence_links(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith(("https://", "http://")) else []
    if isinstance(value, dict):
        return [link for item in value.values() for link in _evidence_links(item)]
    if isinstance(value, (list, tuple)):
        return [link for item in value for link in _evidence_links(item)]
    return []


class JsonReportWriter:
    """Collects scenario results and writes a versioned JSON report."""

    def __init__(
        self,
        *,
        config: AgentTestConfig,
        output_path: Path,
    ) -> None:
        self.config = config
        self.output_path = output_path
        self.run_id = f"pytest_{uuid.uuid4().hex[:12]}"
        self.started_at = datetime.now(UTC)
        self.scenarios: list[ScenarioReport] = []
        self.endpoint_profile: dict[str, str] | None = None
        self.expected_mcp_servers: list[str] = []

    def record_scenario(
        self,
        *,
        name: str,
        nodeid: str,
        passed: bool,
        skipped: bool = False,
        status: ScenarioStatus | None = None,
        duration_ms: int,
        markers: list[str],
        error_message: str | None = None,
        extra: dict[str, Any] | None = None,
        execution_result: AgentExecutionResult | None = None,
        verification_results: Sequence[VerificationResult] = (),
    ) -> None:
        extra = extra or {}
        if execution_result is None:
            candidate = extra.get("execution_result")
            if isinstance(candidate, AgentExecutionResult):
                execution_result = candidate
        tool_calls = (
            execution_result.tool_calls
            if execution_result is not None
            else extra.get("tool_calls", [])
        )
        assertions = (
            [
                AssertionReport.model_validate(assertion.model_dump())
                for assertion in execution_result.assertion_outcomes
            ]
            if execution_result is not None
            else extra.get("assertions", [])
        )
        verification_reports = [
            SideEffectVerificationReport(
                verifier_name=result.verifier_name or "unnamed-verifier",
                passed=result.passed,
                message=result.message,
                evidence=result.evidence,
                evidence_links=_evidence_links(result.evidence),
                duration_ms=result.duration_ms,
                error_type=result.error_type,
                timed_out=result.timed_out,
            )
            for result in verification_results
        ]
        effective_status: ScenarioStatus
        if status is not None:
            effective_status = status
        elif skipped:
            effective_status = "skipped"
        else:
            effective_status = "passed" if passed else "failed"
        security_outcome_failure = any(
            not assertion.passed and "security" in assertion.name.lower()
            for assertion in assertions
        )
        security_verification_failure = any(
            not verification.passed and "security" in verification.verifier_name.lower()
            for verification in verification_reports
        )
        response_payload = execution_result.response if execution_result is not None else {}
        response_dict = response_payload if isinstance(response_payload, dict) else {}
        self.scenarios.append(
            ScenarioReport(
                name=name,
                nodeid=nodeid,
                passed=passed,
                skipped=skipped,
                status=effective_status,
                duration_ms=duration_ms,
                markers=markers,
                run_id=(
                    execution_result.run_id if execution_result is not None else extra.get("run_id")
                ),
                tool_calls=tool_calls,
                timeline=execution_result.trace.events if execution_result is not None else [],
                assertions=assertions,
                side_effect_verifications=verification_reports,
                error_message=error_message,
                retry_count=sum(max(call.attempt - 1, 0) for call in tool_calls),
                token_usage=(
                    execution_result.trace.token_usage if execution_result is not None else None
                ),
                estimated_cost_usd=(
                    execution_result.trace.estimated_cost_usd
                    if execution_result is not None
                    else None
                ),
                duplicate_write_count=count_duplicate_writes(tool_calls),
                security_failure=(
                    ("agent_security" in markers and effective_status in {"failed", "error"})
                    or security_outcome_failure
                    or security_verification_failure
                ),
                scenario_kind=str(
                    extra.get("scenario_kind")
                    or response_dict.get("scenario_kind")
                    or ("prompt_review" if response_dict.get("suggested_prompt") else None)
                ),
                original_prompt=(
                    extra.get("original_prompt")
                    or response_dict.get("original_prompt")
                ),
                suggested_prompt=(
                    extra.get("suggested_prompt")
                    or response_dict.get("suggested_prompt")
                    or response_dict.get("suggestedPrompt")
                ),
                endpoint_base_url=(
                    extra.get("endpoint_base_url") or response_dict.get("endpoint_base_url")
                ),
                connected_mcp_servers=list(
                    extra.get("connected_mcp_servers")
                    or (
                        getattr(execution_result.trace, "connected_mcp_servers", [])
                        if execution_result is not None
                        else []
                    )
                    or response_dict.get("connected_mcp_servers")
                    or []
                ),
                injection_detected=extra.get("injection_detected")
                if extra.get("injection_detected") is not None
                else response_dict.get("injection_detected"),
                expected_mcp_servers=list(
                    extra.get("expected_mcp_servers") or self.expected_mcp_servers or []
                ),
                violation_types=list(
                    extra.get("violation_types")
                    or response_dict.get("violation_types")
                    or []
                ),
                golden_outcome=extra.get("golden_outcome") or response_dict.get("golden_outcome"),
                expected_classification=extra.get("expected_classification")
                or response_dict.get("expected_classification"),
                golden_met=extra.get("golden_met")
                if extra.get("golden_met") is not None
                else response_dict.get("golden_met"),
            )
        )

    def build_report(self) -> AgentTestRunReport:
        report = AgentTestRunReport(
            run_id=self.run_id,
            repository=self.config.repository,
            branch=self.config.branch,
            commit=self.config.commit,
            pipeline_id=self.config.pipeline_id,
            agent_id=self.config.agent_id,
            agent_version=self.config.agent_version,
            model=self.config.model,
            prompt_version=self.config.prompt_version,
            environment=self.config.environment,
            started_at=self.started_at,
            completed_at=datetime.now(UTC),
            scenarios=self.scenarios,
            endpoint_profile=self.endpoint_profile,
            expected_mcp_servers=self.expected_mcp_servers,
        )
        report.finalize_metrics()
        return report

    def write(self, report: AgentTestRunReport | None = None) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        report = report or self.build_report()
        payload = redact_value(report.model_dump(mode="json"))
        self.output_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return self.output_path
