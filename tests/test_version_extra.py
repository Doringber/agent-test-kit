"""Version fallback tests."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from agent_test_kit import _version


@pytest.mark.agent_unit
def test_resolve_version_package_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(_version, "version", _raise)
    monkeypatch.setattr(_version, "_read_version_file", lambda: None)
    assert _version._resolve_version() == "0.0.0-dev"
