"""Runnable guardrail and eval examples.

From a checkout with the package installed:

    python examples/guardrails_and_evals.py
"""

from __future__ import annotations

from agent_test_kit import (
    AgentExecutionResult,
    EvalResult,
    GuardrailMonitor,
    GuardrailReport,
    NoProfanityGuardrail,
    RequiredTermsEval,
    ToolCall,
    check_guardrails,
    eval_case,
    must_open_pull_request,
    response_text,
    run_evals,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.trace import AgentTrace


def _pr_result(response: str) -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="run_example",
        response=response,
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="github",
                    name="create_pull_request",
                    status=ToolCallStatus.SUCCESS,
                    operation_kind=ToolOperationKind.WRITE,
                )
            ]
        ),
    )


def example_offline_guardrail() -> GuardrailReport:
    """Check a recorded trace the same way a pytest test would."""
    result = _pr_result("I opened the pull request.")
    report = check_guardrails(
        result,
        [NoProfanityGuardrail(), must_open_pull_request(server="github")],
    )
    report.assert_passed()
    return report


def example_online_guardrail() -> GuardrailReport:
    """Attach the same guardrails to a live stream of messages and tool calls."""
    monitor = GuardrailMonitor(
        [NoProfanityGuardrail(), must_open_pull_request(server="github")],
        fail_fast=True,
    )

    def on_agent_event(event: dict[str, object]) -> None:
        monitor.handle(event)

    on_agent_event({"type": "message", "role": "assistant", "text": "I opened the pull request."})
    on_agent_event(
        {
            "type": "tool_call",
            "server": "github",
            "name": "create_pull_request",
            "status": "success",
            "operation_kind": "write",
        }
    )
    report = monitor.finish()
    report.assert_passed()
    return report


@eval_case(name="example_mentions_pull_request", threshold=1.0)
def example_mentions_pull_request(result: AgentExecutionResult) -> float:
    """1.0 when the assistant mentions the pull request it opened."""
    text = response_text(result).casefold()
    return 1.0 if "pull request" in text else 0.0


def example_eval() -> EvalResult:
    """Register an eval and score a recorded run."""
    result = _pr_result("I opened the pull request.")
    report = run_evals(
        result,
        [example_mentions_pull_request, RequiredTermsEval(["pull request"])],
    )
    report.assert_passed()
    return report.results[0]


if __name__ == "__main__":
    example_offline_guardrail()
    example_online_guardrail()
    example_eval()
    print("guardrail and eval examples passed")
