"""Shared pytest framework for testing AI agents."""

from __future__ import annotations

from agent_test_kit._version import __version__
from agent_test_kit.assertions.flow import AnyOfStep, FlowAssertionEngine, OptionalStep, ToolStep
from agent_test_kit.cleanup.manager import CleanupManager
from agent_test_kit.client.agent_client import AgentClient
from agent_test_kit.client.config import AgentTestConfig
from agent_test_kit.client.cursor_agent_client import CursorAgentClient
from agent_test_kit.client.prompt_ai_helper_profiles import (
    PromptAiHelperProfile,
    get_profile,
)
from agent_test_kit.client.prompt_review_client import PromptReviewClient
from agent_test_kit.models.execution import AgentExecutionResult, AgentFlowResult, AssertionOutcome
from agent_test_kit.models.run_context import RunContext
from agent_test_kit.publishing import (
    HttpResultPublisher,
    PublishResult,
    ResultPublisher,
    ResultPublisherConfig,
    ResultPublishError,
)
from agent_test_kit.regression import (
    RegressionBehavior,
    RegressionCase,
    RegressionCaseLoadError,
    RegressionEvaluation,
    RegressionExpectedOutcome,
    RegressionRunEvaluation,
    RegressionToolExpectation,
    load_regression_cases,
)
from agent_test_kit.repetition import (
    AsyncAgentExecutor,
    RepeatedExecutionResult,
    run_repeatedly,
)
from agent_test_kit.reporting.html_report import HtmlReportWriter
from agent_test_kit.reporting.json_report import JsonReportWriter
from agent_test_kit.reporting.markdown_status import MarkdownStatusReportWriter
from agent_test_kit.reporting.readiness import ReadinessPolicy, evaluate_readiness, load_report
from agent_test_kit.scoring import (
    ForbiddenTermsScorer,
    RequiredFieldsScorer,
    RequiredTermsScorer,
    Score,
    Scorer,
    response_text,
)
from agent_test_kit.verifiers import (
    SideEffectVerifier,
    VerificationContext,
    VerificationResult,
    VerificationSummary,
    run_verifiers,
)

__all__ = [
    "AgentClient",
    "AgentExecutionResult",
    "AgentFlowResult",
    "AgentTestConfig",
    "AsyncAgentExecutor",
    "AnyOfStep",
    "AssertionOutcome",
    "CleanupManager",
    "CursorAgentClient",
    "FlowAssertionEngine",
    "ForbiddenTermsScorer",
    "HtmlReportWriter",
    "HttpResultPublisher",
    "JsonReportWriter",
    "MarkdownStatusReportWriter",
    "OptionalStep",
    "PromptReviewClient",
    "PromptAiHelperProfile",
    "PublishResult",
    "ReadinessPolicy",
    "RegressionBehavior",
    "RegressionCase",
    "RegressionCaseLoadError",
    "RegressionEvaluation",
    "RegressionExpectedOutcome",
    "RegressionRunEvaluation",
    "RegressionToolExpectation",
    "RepeatedExecutionResult",
    "RequiredFieldsScorer",
    "RequiredTermsScorer",
    "ResultPublishError",
    "ResultPublisher",
    "ResultPublisherConfig",
    "RunContext",
    "Score",
    "Scorer",
    "SideEffectVerifier",
    "ToolStep",
    "VerificationContext",
    "VerificationResult",
    "VerificationSummary",
    "__version__",
    "evaluate_readiness",
    "load_regression_cases",
    "load_report",
    "get_profile",
    "response_text",
    "run_repeatedly",
    "run_verifiers",
]
