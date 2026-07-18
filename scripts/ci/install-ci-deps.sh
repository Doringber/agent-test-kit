#!/usr/bin/env bash
# Install tooling required in the Lambda CI image (matches cicd_for_python_package).
set -euo pipefail

echo "Installing CI OS packages..."
yum -y update
yum -y install git openssh-client

echo "Installing Python CI tools..."
python3 -m pip install --upgrade pip
python3 -m pip install awscli pyyaml twine build
