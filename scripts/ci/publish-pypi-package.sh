#!/usr/bin/env bash
# Build, validate, and publish agent-test-kit to CodeArtifact.
# Follows the Pango cicd_for_python_package / pango-automation-infrastructure pattern.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

source "${ROOT}/scripts/ci/setup-aws-oidc.sh"

DOMAIN="${CODEARTIFACT_DOMAIN:-pango-pypi-server}"
DOMAIN_OWNER="${CODEARTIFACT_DOMAIN_OWNER:-609081136822}"
REPO="${CODEARTIFACT_REPOSITORY:-pango-pypi}"
REGION="${AWS_DEFAULT_REGION}"
PKG_VERSION="$(tr -d '[:space:]' < VERSION)"

if [[ -n "${BITBUCKET_TAG:-}" ]]; then
  TAG_VERSION="${BITBUCKET_TAG#v}"
  if [[ "${TAG_VERSION}" != "${PKG_VERSION}" ]]; then
    echo "Tag version (${TAG_VERSION}) does not match VERSION file (${PKG_VERSION})" >&2
    exit 1
  fi
fi

echo "Login to AWS CodeArtifact (pip)..."
aws codeartifact login \
  --tool pip \
  --repository "${REPO}" \
  --domain "${DOMAIN}" \
  --domain-owner "${DOMAIN_OWNER}" \
  --region "${REGION}"

bash "${ROOT}/scripts/ci/validate-package.sh"

if aws codeartifact list-package-versions \
  --domain "${DOMAIN}" \
  --domain-owner "${DOMAIN_OWNER}" \
  --repository "${REPO}" \
  --format pypi \
  --package agent-test-kit \
  --region "${REGION}" \
  --query "versions[?version=='${PKG_VERSION}']" \
  --output text | grep -q "${PKG_VERSION}"; then
  echo "Version ${PKG_VERSION} already published; skipping upload."
  exit 0
fi

echo "Login to AWS CodeArtifact (twine)..."
aws codeartifact login \
  --tool twine \
  --repository "${REPO}" \
  --domain "${DOMAIN}" \
  --domain-owner "${DOMAIN_OWNER}" \
  --region "${REGION}"

export TWINE_USERNAME=aws
export TWINE_PASSWORD="$(
  aws codeartifact get-authorization-token \
    --domain "${DOMAIN}" \
    --domain-owner "${DOMAIN_OWNER}" \
    --region "${REGION}" \
    --query authorizationToken \
    --output text
)"
export TWINE_REPOSITORY_URL="$(
  aws codeartifact get-repository-endpoint \
    --domain "${DOMAIN}" \
    --domain-owner "${DOMAIN_OWNER}" \
    --repository "${REPO}" \
    --format pypi \
    --query repositoryEndpoint \
    --output text \
    --region "${REGION}"
)"

echo "Uploading agent-test-kit ${PKG_VERSION}..."
twine upload --verbose --repository-url "${TWINE_REPOSITORY_URL}" dist/*

echo "Published agent-test-kit version ${PKG_VERSION}"
