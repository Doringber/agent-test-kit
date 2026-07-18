"""AgentTestConfig tests."""

from __future__ import annotations

import pytest

from agent_test_kit.client.config import AgentTestConfig


@pytest.mark.agent_unit
def test_execute_url() -> None:
    config = AgentTestConfig(base_url="http://agent.test/", execute_path="/run")
    assert config.execute_url == "http://agent.test/run"
