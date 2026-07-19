"""Cleanup manager tests."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

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


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_cleanup_async_context_awaits_general_awaitables_and_clears_callbacks() -> None:
    cleaned: list[str] = []

    class CustomAwaitable:
        def __await__(self) -> Generator[None, None, None]:
            cleaned.append("awaited")
            if False:
                yield
            return None

    async with CleanupManager() as manager:
        manager.register(lambda: CustomAwaitable())

    await manager.run_all()
    assert cleaned == ["awaited"]


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_cleanup_aggregates_unnamed_callback_failures_and_remains_reusable() -> None:
    class FailingCleanup:
        def __call__(self) -> None:
            raise ValueError("cannot clean")

    manager = CleanupManager()
    manager.register(FailingCleanup())

    with pytest.raises(RuntimeError, match=r"FailingCleanup.*cannot clean"):
        await manager.run_all()

    await manager.run_all()


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_async_context_preserves_body_error_when_cleanup_also_fails() -> None:
    def fail_cleanup() -> None:
        raise ValueError("cleanup failed")

    with pytest.raises(LookupError, match="body failed") as captured:
        async with CleanupManager() as manager:
            manager.register(fail_cleanup)
            raise LookupError("body failed")

    assert any("cleanup failed" in note for note in captured.value.__notes__)


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_run_all_finishes_callbacks_and_notes_errors_before_reraising_cancellation() -> None:
    blocker_started = asyncio.Event()
    release_blocker = asyncio.Event()
    events: list[str] = []

    async def blocking_cleanup() -> None:
        events.append("blocking-started")
        blocker_started.set()
        await release_blocker.wait()
        events.append("blocking-finished")

    def failing_cleanup() -> None:
        events.append("failing")
        raise ValueError("cleanup failure during cancellation")

    def final_cleanup() -> None:
        events.append("final")

    manager = CleanupManager()
    manager.register(final_cleanup)
    manager.register(failing_cleanup)
    manager.register(blocking_cleanup)

    cleanup_task = asyncio.create_task(manager.run_all())
    await blocker_started.wait()
    cleanup_task.cancel()
    release_blocker.set()

    with pytest.raises(asyncio.CancelledError) as captured:
        await cleanup_task

    assert events == [
        "blocking-started",
        "blocking-finished",
        "failing",
        "final",
    ]
    assert any("cleanup failure during cancellation" in note for note in captured.value.__notes__)
    await manager.run_all()


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_callback_cancellation_does_not_skip_remaining_cleanup() -> None:
    events: list[str] = []

    async def cancelled_cleanup() -> None:
        events.append("cancelled")
        raise asyncio.CancelledError

    manager = CleanupManager()
    manager.register(lambda: events.append("remaining"))
    manager.register(cancelled_cleanup)

    with pytest.raises(asyncio.CancelledError):
        await manager.run_all()

    assert events == ["cancelled", "remaining"]


@pytest.mark.agent_unit
@pytest.mark.asyncio
async def test_sync_cleanup_context_rejects_running_event_loop() -> None:
    manager = CleanupManager()
    manager.register(lambda: None)

    with pytest.raises(RuntimeError, match="async with"), manager:
        pass
