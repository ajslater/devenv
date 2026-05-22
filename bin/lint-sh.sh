#!/usr/bin/env bash
# Lint shell scripts
set -euxo pipefail

shellcheck --external-sources ./**/*.sh
shellharden --check ./**/*.sh
shfmt --simplify --diff ./**/*.sh
