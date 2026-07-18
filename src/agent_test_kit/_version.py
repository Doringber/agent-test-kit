"""Package version resolution."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_version_file() -> str | None:
    for parent in Path(__file__).resolve().parents:
        version_file = parent / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="utf-8").strip()
    return None


def _resolve_version() -> str:
    try:
        return version("agent-test-kit")
    except PackageNotFoundError:
        pass
    file_version = _read_version_file()
    if file_version:
        return file_version
    return "0.0.0-dev"


__version__ = _resolve_version()
