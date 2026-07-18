"""Verifier protocol dataclass tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.execution import AgentExecutionResult
from agent_test_kit.verifiers.protocols import VerificationContext, VerificationResult


@pytest.mark.agent_unit
def test_verification_context() -> None:
    execution = AgentExecutionResult(success=True, run_id="run_1")
    context = VerificationContext(
        run_id="run_1",
        correlation_id="corr_1",
        execution_result=execution,
    )
    assert context.run_id == "run_1"


@pytest.mark.agent_unit
def test_verification_result_defaults() -> None:
    result = VerificationResult(passed=True)
    assert result.evidence == {}
