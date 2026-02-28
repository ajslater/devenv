#!/usr/bin/env bash
# Read the devenv config file
# Requires yq
set -euo pipefail

DEVENV_SRC=${DEVENV_SRC:-../devenv}
CONFIG_FN="./.devenv.yaml"

unset DEVENV_SRC
DEVENV_SRC=$(yq '.source' "$CONFIG_FN")
if [ "$DEVENV_SRC" == "null" ]; then
  DEVENV_SRC=../devenv
fi
export DEVENV_SRC

while IFS= read -r feature; do
  unset "DEVENV_${feature^^}"
  export "DEVENV_${feature^^}=1"
done < <(yq '.features[]' "$CONFIG_FN")
