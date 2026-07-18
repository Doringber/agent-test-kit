"""Smoke test executed from verify-package.sh against installed wheel."""

from __future__ import annotations

import agent_test_kit
from agent_test_kit import AgentClient, AgentTestConfig


def test_public_api_imports() -> None:
    assert agent_test_kit.__version__
    assert AgentClient is not None
    assert AgentTestConfig is not None
