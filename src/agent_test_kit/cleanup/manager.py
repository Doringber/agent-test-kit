"""Cleanup callback registration for test teardown."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

CleanupCallback = Callable[..., Awaitable[None] | None]


class CleanupManager:
    """Registers cleanup callbacks executed even when assertions fail."""

    def __init__(self) -> None:
        self._callbacks: list[tuple[CleanupCallback, tuple[Any, ...], dict[str, Any]]] = []

    def register(
        self,
        callback: CleanupCallback,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._callbacks.append((callback, args, kwargs))

    async def run_all(self) -> None:
        callbacks = list(reversed(self._callbacks))
        self._callbacks.clear()
        worker = asyncio.create_task(self._run_callbacks(callbacks))
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                errors, callback_cancellation = await asyncio.shield(worker)
                break
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
                if worker.done():
                    try:
                        errors, callback_cancellation = worker.result()
                    except asyncio.CancelledError as worker_cancellation:
                        errors = []
                        callback_cancellation = worker_cancellation
                    break

        cancellation = cancellation or callback_cancellation
        if cancellation is not None:
            if errors:
                cancellation.add_note(self._format_errors(errors))
            raise cancellation
        if errors:
            raise RuntimeError(self._format_errors(errors))

    @staticmethod
    async def _run_callbacks(
        callbacks: list[tuple[CleanupCallback, tuple[Any, ...], dict[str, Any]]],
    ) -> tuple[list[str], asyncio.CancelledError | None]:
        errors: list[str] = []
        cancellation: asyncio.CancelledError | None = None
        for callback, args, kwargs in callbacks:
            try:
                result = callback(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
            except Exception as exc:  # noqa: BLE001 - collect cleanup failures
                callback_name = getattr(callback, "__name__", callback.__class__.__name__)
                errors.append(f"{callback_name}: {exc}")
        return errors, cancellation

    @staticmethod
    def _format_errors(errors: list[str]) -> str:
        return "Cleanup failures: " + "; ".join(errors)

    async def __aenter__(self) -> CleanupManager:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            await self.run_all()
        except RuntimeError as cleanup_error:
            if exc is None:
                raise
            exc.add_note(str(cleanup_error))

    def __enter__(self) -> CleanupManager:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                msg = "CleanupManager must use 'async with' while an event loop is running"
                raise RuntimeError(msg)
            asyncio.run(self.run_all())
        except RuntimeError as cleanup_error:
            if exc is None:
                raise
            exc.add_note(str(cleanup_error))
