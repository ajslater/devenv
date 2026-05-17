#!/usr/bin/env bash
# Initialize a new project
set -euo pipefail
PD=$PWD
mkdir -p bin
DEVENV_SRC=${DEVENV_SRC:-$(realpath "$(dirname "$0")/..")}

# Set feature flags (defaults match add_makefiles.py)
FEATURES=("${@:-common node python}")
if [[ $# -eq 0 ]]; then
  FEATURES=(common node python)
fi
for feature in "${FEATURES[@]}"; do
  export "DEVENV_${feature^^}=1"
done

uv run "$DEVENV_SRC"/scripts/add_makefiles.py "${FEATURES[@]}"
if [[ ${DEVENV_PYTHON:-} ]]; then
  uv init
fi
uv run "$DEVENV_SRC"/scripts/copy_files.py "$PD" --root "$DEVENV_SRC"/init
mv eslint.config.init.js eslint.config.js
uv pip install packaging pathspec semver tomlkit mbake
uv run "$DEVENV_SRC/scripts/update_devenv.py"
