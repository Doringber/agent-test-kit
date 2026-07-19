"""Delay loading the measured pytest plugin until pytest-cov has started."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI options without importing the measured package."""
    group = parser.getgroup("agent-test-kit")
    group.addoption(
        "--agent-report-json",
        action="store",
        default=None,
        help="Write agent test JSON report to this path",
    )
    group.addoption(
        "--agent-report-html",
        action="store",
        default=None,
        help="Write self-contained agent test HTML report to this path",
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Load runtime hooks only after coverage startup is complete."""
    from agent_test_kit.plugin import pytest_plugin

    if not session.config.pluginmanager.has_plugin("agent-test-kit-runtime"):
        session.config.pluginmanager.register(pytest_plugin, "agent-test-kit-runtime")
