#!/usr/bin/env bash
# Set up devenv in the current directory: starter files, feature makefiles and
# a first update. Arguments add features to the defaults; see
# scripts/add_features.py --help. Existing files are never replaced.
set -euo pipefail
DEVENV_SRC=${DEVENV_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git init --quiet
fi
uv run "$DEVENV_SRC/scripts/add_features.py" --init "$@"
make update-devenv DEVENV_SRC="$DEVENV_SRC"
