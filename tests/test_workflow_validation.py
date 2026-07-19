"""Deterministic workflow validation API tests."""

from __future__ import annotations

from typing import Any

import pytest

from agent_test_kit import AgentExecutionResult, AnyOfStep, OptionalStep, ToolStep
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace


def _result(*calls: ToolCall) -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="run-task-2",
        trace=AgentTrace(tool_calls=list(calls)),
    )


def _call(
    name: str,
    *,
    server: str = "svc",
    arguments: dict[str, Any] | None = None,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
    operation: ToolOperationKind = ToolOperationKind.READ,
    attempt: int = 1,
) -> ToolCall:
    return ToolCall(
        server=server,
        name=name,
        arguments=arguments or {},
        status=status,
        operation_kind=operation,
        attempt=attempt,
    )


@pytest.mark.agent_unit
def test_called_validates_status_argument_subset_and_predicate() -> None:
    result = _result(
        _call(
            "search",
            arguments={"query": {"project": "AI", "limit": 20}, "page": 1},
        )
    )

    result.assert_tool_called(
        "search",
        server="svc",
        status=ToolCallStatus.SUCCESS,
        arguments={"query": {"project": "AI"}},
        argument_predicate=lambda arguments: arguments["page"] == 1,
    )

    with pytest.raises(
        AssertionError,
        match=r"Expected arguments subset.*project.*Observed matching calls",
    ):
        result.assert_tool_called("search", arguments={"query": {"project": "BILLING"}})


@pytest.mark.agent_unit
def test_sequence_supports_optional_steps_any_of_and_success_status() -> None:
    result = _result(_call("read"), _call("create", operation=ToolOperationKind.WRITE))

    result.assert_tool_sequence(
        [
            ToolStep("svc", "read", status=ToolCallStatus.SUCCESS),
            OptionalStep(ToolStep("svc", "enrich")),
            AnyOfStep(ToolStep("svc", "create"), ToolStep("svc", "update")),
        ]
    )


@pytest.mark.agent_unit
def test_optional_step_scans_past_extra_reads_before_optional_write() -> None:
    result = _result(
        _call("first"),
        _call("extra_read"),
        _call("optional_write", operation=ToolOperationKind.WRITE),
        _call("last"),
    )

    result.assert_tool_sequence(
        [
            ToolStep("svc", "first"),
            OptionalStep(ToolStep("svc", "optional_write")),
            ToolStep("svc", "last"),
        ],
        allow_additional_read_tools=True,
    )


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    "operation",
    [ToolOperationKind.UNKNOWN, ToolOperationKind.WRITE],
)
def test_optional_step_scan_rejects_nonmatching_unsafe_calls(
    operation: ToolOperationKind,
) -> None:
    result = _result(
        _call("first"),
        _call("unsafe", operation=operation),
        _call("optional_write", operation=ToolOperationKind.WRITE),
        _call("last"),
    )

    with pytest.raises(AssertionError, match="Unexpected non-read tool 'svc/unsafe'"):
        result.assert_tool_sequence(
            [
                ToolStep("svc", "first"),
                OptionalStep(ToolStep("svc", "optional_write")),
                ToolStep("svc", "last"),
            ],
            allow_additional_read_tools=True,
        )


@pytest.mark.agent_unit
def test_status_aware_called_order_and_sequence_ignore_failed_attempts() -> None:
    result = _result(
        _call("read", status=ToolCallStatus.ERROR),
        _call("write", operation=ToolOperationKind.WRITE),
        _call("read"),
    )

    result.assert_tool_called("read", status=ToolCallStatus.SUCCESS)
    result.assert_tool_order(
        before=("svc", "write"),
        after=("svc", "read"),
        status=ToolCallStatus.SUCCESS,
    )
    result.assert_tool_sequence(
        [("svc", "write"), ("svc", "read")],
        status=ToolCallStatus.SUCCESS,
    )


@pytest.mark.agent_unit
def test_count_step_attempt_failure_and_read_only_assertions() -> None:
    successful = _call("read")
    failed_retry = _call("read", status=ToolCallStatus.ERROR, attempt=2)
    result = _result(successful, failed_retry)

    result.assert_tool_call_count(
        "read",
        status=ToolCallStatus.SUCCESS,
        exact=1,
    )
    result.assert_max_workflow_steps(2)
    result.assert_max_tool_attempts(2)
    result.assert_max_retries(1)

    with pytest.raises(AssertionError, match="failed tool calls"):
        result.assert_no_failed_tool_calls()

    unknown = _result(_call("mystery", operation=ToolOperationKind.UNKNOWN))
    with pytest.raises(AssertionError, match=r"read-only.*mystery.*unknown"):
        unknown.assert_read_only()


@pytest.mark.agent_unit
@pytest.mark.parametrize("unsafe_position", ["interstitial", "trailing"])
@pytest.mark.parametrize(
    "operation",
    [ToolOperationKind.UNKNOWN, ToolOperationKind.WRITE],
)
def test_additional_reads_reject_unknown_and_writes_everywhere(
    unsafe_position: str,
    operation: ToolOperationKind,
) -> None:
    unsafe = _call("unsafe", operation=operation)
    calls = [_call("first"), _call("last")]
    calls.insert(1 if unsafe_position == "interstitial" else 2, unsafe)
    result = _result(*calls)

    with pytest.raises(AssertionError, match="Unexpected non-read tool 'svc/unsafe'"):
        result.assert_tool_sequence(
            [("svc", "first"), ("svc", "last")],
            allow_additional_read_tools=True,
        )


@pytest.mark.agent_unit
def test_additional_reads_reject_unsafe_calls_excluded_by_status_filter() -> None:
    result = _result(
        _call("first"),
        _call(
            "unsafe",
            status=ToolCallStatus.ERROR,
            operation=ToolOperationKind.WRITE,
        ),
        _call("last"),
    )

    with pytest.raises(AssertionError, match="Unexpected non-read tool 'svc/unsafe'"):
        result.assert_tool_sequence(
            [("svc", "first"), ("svc", "last")],
            allow_additional_read_tools=True,
            status=ToolCallStatus.SUCCESS,
        )


@pytest.mark.agent_unit
def test_validation_failures_show_expected_and_observed_counts() -> None:
    result = _result(_call("read"))

    with pytest.raises(
        AssertionError,
        match=r"Expected.*between 2 and 3.*Observed: 1",
    ):
        result.assert_tool_call_count("read", min_calls=2, max_calls=3)


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    ("constraints", "message"),
    [
        ({"exact": 1, "min_calls": 1}, "exact is mutually exclusive with min_calls"),
        ({"exact": 1, "max_calls": 1}, "exact is mutually exclusive with max_calls"),
        ({"min_calls": 2, "max_calls": 1}, "min_calls cannot exceed max_calls"),
    ],
)
def test_count_constraints_reject_ambiguous_or_impossible_ranges(
    constraints: dict[str, int],
    message: str,
) -> None:
    result = _result(_call("read"))

    with pytest.raises(ValueError, match=message):
        result.assert_tool_call_count("read", **constraints)
