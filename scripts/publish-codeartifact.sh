#!/usr/bin/env bash
# Publish agent-test-kit to AWS CodeArtifact via twine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

: "${CODEARTIFACT_DOMAIN:=pango-pypi-server}"
: "${CODEARTIFACT_DOMAIN_OWNER:=609081136822}"
: "${CODEARTIFACT_REPOSITORY:=pango-pypi}"
: "${AWS_DEFAULT_REGION:=eu-west-1}"

if [[ ! -d dist ]] || [[ -z "$(ls -A dist 2>/dev/null)" ]]; then
  echo "No dist/ artifacts found. Run scripts/build-package.sh first." >&2
  exit 1
fi

echo "Authenticating to CodeArtifact (domain=${CODEARTIFACT_DOMAIN}, repo=${CODEARTIFACT_REPOSITORY})..."
aws codeartifact login \
  --tool twine \
  --domain "${CODEARTIFACT_DOMAIN}" \
  --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
  --repository "${CODEARTIFACT_REPOSITORY}" \
  --region "${AWS_DEFAULT_REGION}"

echo "Uploading package to CodeArtifact..."
twine upload --repository codeartifact dist/*

VERSION="$(tr -d '[:space:]' < VERSION)"
echo "Published agent-test-kit version ${VERSION}"
