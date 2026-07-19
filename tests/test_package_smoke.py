"""Smoke test executed from verify-package.sh against installed wheel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import agent_test_kit
from agent_test_kit import AgentClient, AgentTestConfig


def test_public_api_imports() -> None:
    assert agent_test_kit.__version__
    assert AgentClient is not None
    assert AgentTestConfig is not None


def test_pytest_entrypoint_does_not_import_measured_package_early() -> None:
    source_path = Path(__file__).parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import agent_test_kit_pytest_entrypoint; "
                "assert 'agent_test_kit' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
