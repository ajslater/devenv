#!/bin/bash
# Initialize a new project
set -euo pipefail
DEVENV=../devenv
mkdir -p bin
cp -a "$DEVENV"/bin/* bin/ || true
cp -an "$DEVENV"/init/* "$DEVENV"/init/.* . || true
uv pip install semver tomlkit
bin/update-devenv.sh
