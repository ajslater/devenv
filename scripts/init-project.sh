#!/usr/bin/env bash
# Initialize a new project
set -euo pipefail
mkdir -p bin
DEVENV_SRC=${1:-${DEVEVN_SRC:-../devenv}}
export DEVENV_COMMON=1
"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/bin bin
"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/init .
uv pip install semver tomlkit
source "$DEVENV_SRC"/scripts/parse-config.sh
"$DEVENV_SRC/scripts/update-devenv.sh"
