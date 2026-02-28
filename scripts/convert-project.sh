#!/usr/bin/env bash
# Upgrade an old project based on aj's boilerplate repo to devenv managed
set -euo pipefail
DEVENV_SRC=${1:-${DEVEVN_SRC:-../devenv}}
mv Makefile Makefile.orig.mk
mv eslint.config.js eslint.config.orig.js
"$DEVENV_SRC"/scripts/init-project.sh
