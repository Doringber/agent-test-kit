#!/usr/bin/env bash
# Build the agent-test-kit wheel and source distribution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

rm -rf dist build *.egg-info src/*.egg-info 2>/dev/null || true
python -m build

echo "Build complete. Artifacts:"
ls -la dist/
