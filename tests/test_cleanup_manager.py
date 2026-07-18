"""Cleanup manager tests."""

from __future__ import annotations

import pytest

from agent_test_kit.cleanup.manager import CleanupManager


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_cleanup_runs_in_reverse_order() -> None:
    order: list[str] = []

    async def first() -> None:
        order.append("first")

    def second() -> None:
        order.append("second")

    manager = CleanupManager()
    manager.register(first)
    manager.register(second)
    await manager.run_all()
    assert order == ["second", "first"]


@pytest.mark.agent_unit
def test_cleanup_context_manager() -> None:
    cleaned: list[str] = []

    with CleanupManager() as manager:
        manager.register(lambda: cleaned.append("done"))
    assert cleaned == ["done"]
