#!/usr/bin/env bash
# Upgrade an old project based on aj's boilerplate repo to devenv managed
set -euo pipefail
DEVENV_SRC=${DEVENV_SRC:-$(realpath "$(dirname "$0")/..")}
mv Makefile Makefile.orig.mk
mv eslint.config.js eslint.config.orig.js
"$DEVENV_SRC"/scripts/init-project.sh "$@"
