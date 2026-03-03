#!/usr/bin/env bash
# copy specific makefiles
set -euo pipefail
set -x
DEVENV_SRC=${DENENV_SRC:-$(realpath "$(dirname "$0")/..")}

for feature in "$@"; do
  export "DEVENV_${feature^^}=1"
done

"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/cfg "$PWD"/cfg
uv run mbake format Makefile cfg/*.mk
