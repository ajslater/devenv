#!/usr/bin/env bash
# Initialize a new project
set -euo pipefail
PD=$PWD
mkdir -p bin
DEVENV_SRC=${DENENV_SRC:-$(realpath "$(dirname "$0")/..")}
source "$DEVENV_SRC"/scripts/add-makefiles.sh "$@"
if [[ ${DEVENV_PYTHON:-} ]]; then
  uv init
fi
"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/bin "$PD"/bin
"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/init "$PD"
uv pip install packaging semver tomlkit
"$DEVENV_SRC/scripts/update-devenv.sh"
