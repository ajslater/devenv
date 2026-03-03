#!/usr/bin/env bash
# copy specific makefiles
set -euo pipefail
DEVENV_SRC=${DENENV_SRC:-$(realpath "$(dirname "$0")/..")}

while getopts "h?:" opt; do
  case "$opt" in
    h | \?)
      source "$DEVENV_SRC"/scripts/all-features.sh
      echo Features: "${ALL_FEATURES[@]}"
      exit 1
      ;;
  esac
done

if [[ ${#@} -gt 0 ]]; then
  FEATURES=("$@")
else
  FEATURES=(common node_root python)
fi
echo Adding features: "${FEATURES[@]}"
for feature in "${FEATURES[@]}"; do
  export "DEVENV_${feature^^}=1"
done

"$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC"/cfg "$PWD"/cfg
uv run mbake format Makefile cfg/*.mk
