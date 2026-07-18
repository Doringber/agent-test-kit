#!/usr/bin/env bash
# Build, validate, and smoke-test the agent-test-kit wheel in a clean venv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> Building package"
bash scripts/build-package.sh

echo "==> Running twine check"
twine check dist/*

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

echo "==> Creating clean virtual environment at ${TMPDIR}/venv"
python3 -m venv "${TMPDIR}/venv"
# shellcheck disable=SC1091
source "${TMPDIR}/venv/bin/activate"
python -m pip install --upgrade pip --quiet

WHEEL="$(ls dist/*.whl | head -1)"
echo "==> Installing wheel: ${WHEEL}"
pip install "${WHEEL}" --quiet

echo "==> Import smoke test"
python -c "
import agent_test_kit
print(f'Installed agent-test-kit version: {agent_test_kit.__version__}')
assert agent_test_kit.__version__
"

echo "==> Running package smoke test"
python -c "
from agent_test_kit import AgentClient, AgentExecutionResult, AgentTestConfig
from agent_test_kit.models.tool_call import ToolCall
from agent_test_kit.models.trace import AgentTrace

client = AgentClient(AgentTestConfig(agent_id='smoke-agent'))
context = client.new_run_context()
assert context.run_id.startswith('run_')

result = AgentExecutionResult(
    success=True,
    run_id=context.run_id,
    trace=AgentTrace(tool_calls=[ToolCall(server='bitbucket', name='get_pull_request')]),
)
result.assert_tool_called('get_pull_request', server='bitbucket')
print('Smoke test passed')
"

echo "==> verify-package.sh completed successfully"
