#!/bin/bash
# Initialize a new project
set -euo pipefail
DEVENV=../devenv
mkdir -p bin
"$DEVENV"/bin/copy-new-files.sh "$DEVENV"/bin bin
"$DEVENV"/bin/copy-new-files.sh "$DEVENV"/init .
uv pip install semver tomlkit
bin/update-devenv.sh
