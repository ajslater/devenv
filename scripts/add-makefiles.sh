#!/usr/bin/env bash
# copy specific makefiles
set -euo pipefail
DEVENV_SRC=${DENENV_SRC:-$(realpath "$(dirname "$0")/..")}
DEFAULT_FEATURES=(common node_root python)
if [[ ${#@} -gt 0 ]]; then
  FEATURES=("$@")
else
  FEATURES=("${DEFAULT_FEATURES[@]}")
fi

for feature in "${FEATURES[@]}"; do
  export "DEVENV_${feature^^}=1"
done

"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/cfg "$PWD"/cfg
uv run mbake format Makefile cfg/*.mk
