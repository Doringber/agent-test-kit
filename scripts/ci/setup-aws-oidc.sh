#!/usr/bin/env bash
# Configure AWS OIDC credentials for Bitbucket Pipelines (Pango standard).
set -euo pipefail

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
export AWS_REGION="${AWS_DEFAULT_REGION}"
export AWS_ROLE_ARN="${AWS_ROLE_ARN:-arn:aws:iam::609081136822:role/Bitbucket-Pipeline-Deploy-Serverless-App}"
export AWS_WEB_IDENTITY_TOKEN_FILE="${AWS_WEB_IDENTITY_TOKEN_FILE:-$(pwd)/web-identity-token}"

echo "${BITBUCKET_STEP_OIDC_TOKEN}" > "${AWS_WEB_IDENTITY_TOKEN_FILE}"
