#!/usr/bin/env bash
# Validate agent-test-kit (lint, typecheck, tests, build, twine check).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

python3 -m pip install -e ".[dev]"

ruff check .
ruff format --check .
mypy src

mkdir -p reports
bash scripts/run-tests.sh

python3 -m build
twine check dist/*
