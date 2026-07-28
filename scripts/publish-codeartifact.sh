#!/usr/bin/env bash
# Publish agent-test-kit to AWS CodeArtifact via twine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

: "${CODEARTIFACT_DOMAIN:?Set CODEARTIFACT_DOMAIN}"
: "${CODEARTIFACT_DOMAIN_OWNER:?Set CODEARTIFACT_DOMAIN_OWNER}"
: "${CODEARTIFACT_REPOSITORY:?Set CODEARTIFACT_REPOSITORY}"
: "${AWS_DEFAULT_REGION:=eu-west-1}"

if [[ ! -d dist ]] || [[ -z "$(ls -A dist 2>/dev/null)" ]]; then
  echo "No dist/ artifacts found. Run scripts/build-package.sh first." >&2
  exit 1
fi

echo "Login to AWS CodeArtifact (twine)..."
aws codeartifact login \
  --tool twine \
  --domain "${CODEARTIFACT_DOMAIN}" \
  --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
  --repository "${CODEARTIFACT_REPOSITORY}" \
  --region "${AWS_DEFAULT_REGION}"

export TWINE_USERNAME=aws
export TWINE_PASSWORD="$(
  aws codeartifact get-authorization-token \
    --domain "${CODEARTIFACT_DOMAIN}" \
    --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
    --region "${AWS_DEFAULT_REGION}" \
    --query authorizationToken \
    --output text
)"
export TWINE_REPOSITORY_URL="$(
  aws codeartifact get-repository-endpoint \
    --domain "${CODEARTIFACT_DOMAIN}" \
    --domain-owner "${CODEARTIFACT_DOMAIN_OWNER}" \
    --repository "${CODEARTIFACT_REPOSITORY}" \
    --format pypi \
    --query repositoryEndpoint \
    --output text \
    --region "${AWS_DEFAULT_REGION}"
)"

echo "Uploading package to CodeArtifact..."
twine upload --verbose --repository-url "${TWINE_REPOSITORY_URL}" dist/*

VERSION="$(tr -d '[:space:]' < VERSION)"
echo "Published agent-test-kit version ${VERSION}"
