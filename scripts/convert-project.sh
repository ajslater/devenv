#!/usr/bin/env bash
# Convert a project from aj's old boilerplate to devenv. Like init-project.sh,
# but the old Makefile and eslint.config.js are kept as *.orig.* files to copy
# project-specific parts from.
set -euo pipefail
DEVENV_SRC=${DEVENV_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

uv run "$DEVENV_SRC/scripts/add_features.py" --convert "$@"
make update-devenv DEVENV_SRC="$DEVENV_SRC"
