#!/usr/bin/env bash
# Read the devenv config file
# Requires yq
set -euo pipefail

DEVENV_SRC=${DEVENV_SRC:-../devenv}
export DEVENV_SRC
CONFIG_FN="./.devenv.yaml"

while IFS= read -r feature; do
  unset "DEVENV_${feature^^}"
  export "DEVENV_${feature^^}=1"
done < <(yq '.features[]' "$CONFIG_FN")
