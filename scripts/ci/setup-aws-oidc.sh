#!/usr/bin/env bash
# Configure AWS OIDC credentials for CI publish jobs.
set -euo pipefail

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
export AWS_REGION="${AWS_DEFAULT_REGION}"
export AWS_ROLE_ARN="${AWS_ROLE_ARN:?Set AWS_ROLE_ARN for OIDC publish}"
export AWS_WEB_IDENTITY_TOKEN_FILE="${AWS_WEB_IDENTITY_TOKEN_FILE:-$(pwd)/web-identity-token}"

echo "${BITBUCKET_STEP_OIDC_TOKEN}" > "${AWS_WEB_IDENTITY_TOKEN_FILE}"
