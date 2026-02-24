#!/bin/bash
# Upgrade an old project based on aj's boilerplate repo to devenv managed
set -euo pipefail
DEVENV=../devenv
mv Makefile Makefile.orig.mk
mv eslint.config.js eslint.config.orig.js
"$DEVENV"/init-project.sh
