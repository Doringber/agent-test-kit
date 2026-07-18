"""Enum model tests."""

from __future__ import annotations

import pytest

from agent_test_kit.models.enums import ToolCallStatus, ToolOperationKind


@pytest.mark.agent_unit
def test_tool_call_status_values() -> None:
    assert ToolCallStatus.SUCCESS == "success"
    assert ToolCallStatus.ERROR == "error"


@pytest.mark.agent_unit
def test_tool_operation_kind_values() -> None:
    assert ToolOperationKind.READ == "read"
    assert ToolOperationKind.WRITE == "write"
