"""Version resolution tests."""

from __future__ import annotations

import agent_test_kit
from agent_test_kit._version import _read_version_file, _resolve_version


def test_version_is_semver_like() -> None:
    version = agent_test_kit.__version__
    parts = version.split(".")
    assert len(parts) >= 2
    assert parts[0].isdigit()


def test_read_version_file() -> None:
    assert _read_version_file() == "0.1.1"


def test_resolve_version_matches_file() -> None:
    assert _resolve_version() == "0.1.1"
