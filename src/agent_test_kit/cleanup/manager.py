"""Cleanup callback registration for test teardown."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
        errors: list[str] = []
        for callback, args, kwargs in reversed(self._callbacks):
            try:
                result = callback(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - collect cleanup failures
                errors.append(f"{callback.__name__}: {exc}")
        if errors:
            raise RuntimeError("Cleanup failures: " + "; ".join(errors))

    def __enter__(self) -> CleanupManager:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        asyncio.run(self.run_all())
