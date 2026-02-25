#!/bin/bash
# Initialize a new project
set -euo pipefail
mkdir -p bin
export DEVENV_COMMON=1
"$DEVENV"/bin/copy-new-files.sh "$DEVENV"/bin bin
"$DEVENV"/bin/copy-new-files.sh "$DEVENV"/init .
uv pip install semver tomlkit
source "$PD"/scripts/parse-config.sh "$DEVENV"
"$DEVENV/scripts/update-devenv.sh"
