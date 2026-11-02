"""Guardrails: offline traces, live hooks, and known-good / known-bad traces."""

from __future__ import annotations

from typing import Any

import pytest

from agent_test_kit import (
    AgentExecutionResult,
    Guardrail,
    GuardrailEvent,
    GuardrailMonitor,
    GuardrailViolationError,
    NoProfanityGuardrail,
    RequiredFinalToolGuardrail,
    ToolCall,
    check_guardrails,
    guardrail,
    must_open_pull_request,
)
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.trace import AgentTrace
from agent_test_kit.plugin import pytest_plugin
from agent_test_kit.scoring import response_text

pytestmark = pytest.mark.agent_unit


def _result(
    response: str = "",
    calls: list[ToolCall] | None = None,
    *,
    success: bool = True,
) -> AgentExecutionResult:
    return AgentExecutionResult(
        success=success,
        run_id="run-guard",
        response=response,
        trace=AgentTrace(tool_calls=list(calls or [])),
    )


def _call(
    name: str,
    *,
    server: str | None = None,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
) -> ToolCall:
    return ToolCall(
        server=server,
        name=name,
        status=status,
        operation_kind=ToolOperationKind.WRITE,
    )


def _run_both(guard: Guardrail, result: AgentExecutionResult) -> tuple[bool, bool]:
    """One guardrail definition, offline against the trace and online as a stream."""
    offline = check_guardrails(result, guard)
    monitor = GuardrailMonitor([guard])
    text = response_text(result)
    if text:
        monitor.on_message(text)
    for call in result.tool_calls:
        monitor.on_tool_call(call)
    online = monitor.finish(result)
    return offline.passed, online.passed


@pytest.mark.parametrize(
    ("response", "expect_pass"),
    [
        ("I opened the pull request.", True),
        ("What the fuck is this diff?", False),
        ("SHIT, that failed.", False),
    ],
)
def test_no_profanity_guardrail_known_traces(response: str, expect_pass: bool) -> None:
    guard = NoProfanityGuardrail()
    offline_passed, online_passed = _run_both(guard, _result(response))
    assert offline_passed is expect_pass
    assert online_passed is expect_pass
    report = check_guardrails(_result(response), guard)
    if expect_pass:
        report.assert_passed()
    else:
        with pytest.raises(AssertionError, match="no_profanity"):
            report.assert_passed()


@pytest.mark.parametrize(
    ("calls", "expect_pass"),
    [
        (
            [_call("get_diff", server="github"), _call("create_pull_request", server="github")],
            True,
        ),
        (
            [_call("create_pull_request", server="github"), _call("add_comment", server="github")],
            False,
        ),
        ([], False),
        (
            [_call("create_pull_request", server="github", status=ToolCallStatus.ERROR)],
            False,
        ),
    ],
)
def test_required_final_tool_guardrail_known_traces(
    calls: list[ToolCall],
    expect_pass: bool,
) -> None:
    guard = RequiredFinalToolGuardrail("create_pull_request", server="github")
    offline_passed, online_passed = _run_both(guard, _result("done", calls))
    assert offline_passed is expect_pass
    assert online_passed is expect_pass
    report = check_guardrails(_result("done", calls), guard)
    if expect_pass:
        report.assert_passed()
    else:
        with pytest.raises(AssertionError, match="required_final_tool"):
            report.assert_passed()


@pytest.mark.parametrize(
    ("calls", "expect_pass"),
    [
        ([_call("get_diff", server="github"), _call("create_pull_request", server="github")], True),
        ([_call("create_pull_request", server="github"), _call("add_comment")], False),
        ([], False),
    ],
)
def test_must_open_pull_request_known_traces(calls: list[ToolCall], expect_pass: bool) -> None:
    guard = must_open_pull_request(server="github")
    offline_passed, online_passed = _run_both(guard, _result("I opened the pull request.", calls))
    assert offline_passed is expect_pass
    assert online_passed is expect_pass
    report = check_guardrails(_result("opening", calls), [guard])
    if expect_pass:
        report.assert_passed()
    else:
        with pytest.raises(AssertionError, match="must_open_pull_request"):
            report.assert_passed()


def test_online_profanity_fails_fast_on_the_stream() -> None:
    monitor = GuardrailMonitor([NoProfanityGuardrail()], fail_fast=True)
    with pytest.raises(GuardrailViolationError, match="no_profanity") as caught:
        monitor.handle({"type": "message", "role": "assistant", "text": "fuck this"})
    assert caught.value.violation.phase == "message"
    assert monitor.last_report is not None
    assert not monitor.last_report.passed


def test_online_pull_request_rule_uses_the_same_guardrail() -> None:
    monitor = GuardrailMonitor([must_open_pull_request(server="github")])
    monitor.handle({"type": "message", "content": "I opened the pull request."})
    monitor.handle(
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
    assert report.mode == "online"
    assert report.checks[0].name == "must_open_pull_request"


def test_online_split_profanity_is_caught_when_the_run_finishes() -> None:
    monitor = GuardrailMonitor([NoProfanityGuardrail()])
    monitor.on_message("fu")
    monitor.on_message("ck")
    report = monitor.finish()
    assert not report.passed
    assert report.checks[0].message is not None
    assert "fuck" in report.checks[0].message


def test_user_messages_are_not_agent_output() -> None:
    monitor = GuardrailMonitor([NoProfanityGuardrail()])
    monitor.on_message("fuck", role="user")
    monitor.finish().assert_passed()


def test_word_boundaries_and_custom_disallowed_language() -> None:
    check_guardrails(_result("classic classification"), NoProfanityGuardrail()).assert_passed()
    check_guardrails(_result("a shitake mushroom"), NoProfanityGuardrail()).assert_passed()
    custom = NoProfanityGuardrail(terms=["banana"], extra_terms=["system prompt"])
    check_guardrails(_result("fuck"), custom).assert_passed()
    bad = check_guardrails(_result("leaked the system prompt"), custom)
    assert not bad.passed
    assert "system prompt" in (bad.checks[0].message or "")


def test_profanity_terms_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        NoProfanityGuardrail(terms=[])
    with pytest.raises(ValueError, match="non-empty"):
        NoProfanityGuardrail(extra_terms=["  "])


def test_final_tool_wrong_server_and_optional_success() -> None:
    calls = [_call("create_pull_request", server="bitbucket")]
    report = check_guardrails(
        _result("done", calls),
        RequiredFinalToolGuardrail("create_pull_request", server="github"),
    )
    assert not report.passed
    assert "bitbucket/create_pull_request" in (report.checks[0].message or "")
    allowed = RequiredFinalToolGuardrail(
        "create_pull_request",
        require_success=False,
    )
    errored = [_call("create_pull_request", status=ToolCallStatus.ERROR)]
    check_guardrails(_result("done", errored), allowed).assert_passed()


def test_assert_guardrails_records_a_failure_before_raising() -> None:
    result = _result("fuck")
    with pytest.raises(AssertionError, match="no_profanity"):
        result.assert_guardrails(NoProfanityGuardrail())
    assert result.assertion_outcomes[-1].name == "assert_guardrails"
    assert result.assertion_outcomes[-1].passed is False
    assert result.guardrail_checks[0].passed is False


def test_assert_guardrails_passes_and_records() -> None:
    calls = [_call("create_pull_request", server="github")]
    result = _result("I opened the pull request.", calls)
    report = result.assert_guardrails(
        [NoProfanityGuardrail(), must_open_pull_request(server="github")]
    )
    assert report.passed
    assert result.assertion_outcomes[-1].passed is True
    assert [check.name for check in result.guardrail_checks] == [
        "no_profanity",
        "must_open_pull_request",
    ]


def test_custom_guardrail_decorator_and_subclass_share_both_modes() -> None:
    @guardrail(phase="message")
    def no_secrets(text: str, *, role: str = "assistant") -> str | None:
        if role == "assistant" and "sk-" in text:
            return "assistant output looks like a secret key"
        return None

    class NoDeleteGuardrail(Guardrail):
        name = "no_delete"

        def on_tool_call(self, call: ToolCall) -> str | None:
            if call.name.startswith("delete_"):
                return f"delete tool is not allowed: {call.name}"
            return None

    @guardrail
    def needs_success(result: AgentExecutionResult) -> str | None:
        if not result.success:
            return "run failed"
        return None

    secret = _result("token sk-live")
    assert _run_both(no_secrets, secret) == (False, False)
    deleted = _result("ok", [_call("delete_issue")])
    assert _run_both(NoDeleteGuardrail(), deleted) == (False, False)
    clean = _result("ok", [_call("create_pull_request")])
    assert _run_both(no_secrets, clean) == (True, True)
    assert _run_both(needs_success, _result("ok", success=False)) == (False, False)
    no_role = guardrail(phase="message", name="no_email")(
        lambda text: "email" if "@" in text else None
    )
    assert not check_guardrails(_result("a@b.test"), no_role).passed


def test_guardrail_return_type_and_empty_selection() -> None:
    @guardrail(name="bad_return")
    def bad_return(result: AgentExecutionResult) -> Any:
        return 1

    with pytest.raises(TypeError, match="bad_return"):
        check_guardrails(_result("ok"), bad_return)
    with pytest.raises(ValueError, match="at least one"):
        check_guardrails(_result("ok"), [])
    with pytest.raises(ValueError, match="at least one"):
        GuardrailMonitor([])
    with pytest.raises(TypeError, match="Guardrail"):
        check_guardrails(_result("ok"), ["nope"])  # type: ignore[arg-type]


def test_monitor_rejects_a_second_finish_and_unknown_events() -> None:
    monitor = GuardrailMonitor(NoProfanityGuardrail())
    monitor.finish()
    with pytest.raises(RuntimeError, match="already"):
        monitor.finish()
    with pytest.raises(RuntimeError, match="already"):
        monitor.on_message("hi")
    fresh = GuardrailMonitor(NoProfanityGuardrail())
    with pytest.raises(ValueError, match="Unknown"):
        fresh.handle({"type": "pause"})
    with pytest.raises(ValueError, match="name"):
        fresh.handle({"type": "tool_call"})
    event = GuardrailEvent(
        type="tool_call",
        tool_call=_call("create_pull_request", server="github"),
    )
    assert fresh.handle(event) == []


def test_fixture_records_online_violation_for_the_report(
    agent_guardrails: Any,
    request: pytest.FixtureRequest,
) -> None:
    monitor = agent_guardrails.monitor([NoProfanityGuardrail()], fail_fast=True)
    with pytest.raises(GuardrailViolationError):
        monitor.on_message("fuck")
    agent_guardrails.close()
    state = request.config.stash[pytest_plugin._STASH_KEY]
    checks = state.guardrail_checks[request.node.nodeid]
    assert checks[0].mode == "online"
    assert checks[0].passed is False
    assert "fuck" in (checks[0].message or "")


def test_fixture_offline_check_fails_a_known_bad_trace(agent_guardrails: Any) -> None:
    result = _result("fuck")
    with pytest.raises(AssertionError, match="no_profanity"):
        agent_guardrails.check(result, NoProfanityGuardrail())
    assert result.guardrail_checks[0].passed is False
