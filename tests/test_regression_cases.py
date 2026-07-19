"""Regression case schema, loading, and evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_test_kit import AgentExecutionResult
from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace
from agent_test_kit.regression import (
    RegressionCase,
    RegressionCaseLoadError,
    RegressionToolExpectation,
    load_regression_cases,
)


def _case_payload() -> dict[str, object]:
    return {
        "id": "jira-create-001",
        "source": "AI-42",
        "description": "Create one issue after searching",
        "input": {"summary": "Regression"},
        "expected_outcome": {
            "success": True,
            "required_tools": [
                {
                    "server": "jira",
                    "name": "search",
                    "arguments": {"project": "AI"},
                },
                {
                    "server": "jira",
                    "name": "create",
                    "arguments": {"fields": {"summary": "Regression"}},
                    "exact_calls": 1,
                },
            ],
            "forbidden_tools": [{"server": "jira", "name": "delete"}],
            "order": [
                {"server": "jira", "name": "search"},
                {"server": "jira", "name": "create"},
            ],
            "no_failed_calls": True,
        },
        "tags": ["jira", "write"],
        "created_at": "2026-07-18T12:00:00Z",
    }


def _matching_result() -> AgentExecutionResult:
    return AgentExecutionResult(
        success=True,
        run_id="regression",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="jira",
                    name="search",
                    arguments={"project": "AI", "limit": 50},
                    status=ToolCallStatus.SUCCESS,
                    operation_kind=ToolOperationKind.READ,
                ),
                ToolCall(
                    server="jira",
                    name="create",
                    arguments={"fields": {"summary": "Regression", "description": "details"}},
                    status=ToolCallStatus.SUCCESS,
                    operation_kind=ToolOperationKind.WRITE,
                ),
            ]
        ),
    )


@pytest.mark.agent_unit
@pytest.mark.parametrize("extension", [".json", ".yaml"])
def test_load_regression_cases_from_json_and_yaml(
    tmp_path: Path,
    extension: str,
) -> None:
    path = tmp_path / f"cases{extension}"
    payload = {"cases": [_case_payload()]}
    if extension == ".json":
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(
            """
cases:
  - id: jira-create-001
    source: AI-42
    description: Create one issue after searching
    input:
      summary: Regression
    expected_outcome:
      success: true
      required_tools:
        - server: jira
          name: search
    tags: [jira, write]
    created_at: 2026-07-18T12:00:00Z
""",
            encoding="utf-8",
        )

    cases = load_regression_cases(path)

    assert len(cases) == 1
    assert isinstance(cases[0], RegressionCase)
    assert cases[0].id == "jira-create-001"


@pytest.mark.agent_unit
def test_loader_validation_error_has_file_and_case_context(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(
        """
cases:
  - id: valid
    source: AI-1
    description: valid
    input: {}
    expected_outcome: {success: true}
    tags: []
    created_at: 2026-07-18T12:00:00Z
  - id: broken-case
    source: AI-2
    input: {}
    expected_outcome: {success: true}
    tags: []
    created_at: not-a-date
""",
        encoding="utf-8",
    )

    with pytest.raises(
        RegressionCaseLoadError,
        match=r"invalid.yaml.*case\[1\].*broken-case.*description|"
        r"invalid.yaml.*case\[1\].*broken-case.*created_at",
    ):
        load_regression_cases(path)


@pytest.mark.agent_unit
def test_regression_case_evaluate_passes_declared_expectations() -> None:
    case = RegressionCase.model_validate(_case_payload())

    evaluation = case.evaluate(_matching_result())

    assert evaluation.passed
    assert evaluation.failures == ()
    evaluation.assert_passed()


@pytest.mark.agent_unit
def test_regression_case_evaluate_collects_deterministic_failures() -> None:
    case = RegressionCase.model_validate(_case_payload())
    result = AgentExecutionResult(
        success=False,
        run_id="failed",
        error="agent failed",
        trace=AgentTrace(
            tool_calls=[
                ToolCall(
                    server="jira",
                    name="delete",
                    status=ToolCallStatus.ERROR,
                    operation_kind=ToolOperationKind.WRITE,
                )
            ]
        ),
    )

    evaluation = case.evaluate(result)

    assert not evaluation.passed
    assert evaluation.failures[0] == "Expected success=True. Observed: False"
    assert any("required tool" in failure.lower() for failure in evaluation.failures)
    assert any("forbidden tool" in failure.lower() for failure in evaluation.failures)
    assert any("failed tool calls" in failure.lower() for failure in evaluation.failures)
    with pytest.raises(AssertionError, match=r"jira-create-001.*Expected success=True"):
        evaluation.assert_passed()


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    "constraints",
    [
        {"exact_calls": 1, "min_calls": 1},
        {"exact_calls": 1, "max_calls": 1},
        {"min_calls": 2, "max_calls": 1},
    ],
)
def test_regression_tool_expectation_validates_count_constraints(
    constraints: dict[str, int],
) -> None:
    with pytest.raises(ValidationError, match="count constraints"):
        RegressionToolExpectation.model_validate({"name": "search", **constraints})


@pytest.mark.agent_unit
@pytest.mark.parametrize(
    "constraints",
    [
        {"exact_calls": 1, "min_calls": 1},
        {"exact_calls": 1, "max_calls": 1},
        {"min_calls": 2, "max_calls": 1},
    ],
)
def test_loader_wraps_count_constraint_errors_with_file_and_case_context(
    tmp_path: Path,
    constraints: dict[str, int],
) -> None:
    payload = _case_payload()
    required_tools = payload["expected_outcome"]["required_tools"]  # type: ignore[index]
    required_tools[0].update(constraints)  # type: ignore[index, union-attr]
    path = tmp_path / "invalid-counts.json"
    path.write_text(json.dumps({"cases": [payload]}), encoding="utf-8")

    with pytest.raises(
        RegressionCaseLoadError,
        match=r"invalid-counts.json.*case\[0\].*jira-create-001.*count constraints",
    ):
        load_regression_cases(path)


@pytest.mark.agent_unit
def test_regression_count_uses_required_tool_argument_and_status_filters() -> None:
    payload = _case_payload()
    case = RegressionCase.model_validate(payload)
    result = _matching_result()
    result.trace.tool_calls.extend(
        [
            ToolCall(
                server="jira",
                name="create",
                arguments={"fields": {"summary": "Different"}},
                status=ToolCallStatus.SUCCESS,
                operation_kind=ToolOperationKind.WRITE,
            ),
            ToolCall(
                server="jira",
                name="create",
                arguments={"fields": {"summary": "Regression"}},
                status=ToolCallStatus.PENDING,
                operation_kind=ToolOperationKind.WRITE,
            ),
        ]
    )

    evaluation = case.evaluate(result)

    assert evaluation.passed, evaluation.failures
