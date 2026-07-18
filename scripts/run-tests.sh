#!/usr/bin/env bash
# Run the full test suite with accurate coverage for the pytest plugin package.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

mkdir -p reports

coverage run --source=agent_test_kit -m pytest \
  --junitxml=reports/junit.xml \
  "$@"

coverage report --fail-under=85
coverage xml -o coverage.xml
