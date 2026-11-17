#!/usr/bin/env bash
# Fix or lint the shell and Python files of a directory that is not a devenv
# project, such as ~/bin, with devenv's own tools and flags:
#   scripts/fix-dir.sh [--lint] [DIR]
# DIR, the current directory by default, chooses its files and rules: its
# .shellignore (bin/find-files.sh has the syntax) and its ruff config, which
# can extend devenv's with extend = "<devenv>/pyproject.toml".
set -euo pipefail
devenv=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
  echo "usage: $0 [--lint] [DIR]" >&2
  exit 2
}

mode=--fix
dir=.
dirs=0
for arg in "$@"; do
  case $arg in
  --lint) mode=--lint ;;
  -*) usage ;;
  *)
    dir=$arg
    dirs=$((dirs + 1))
    ;;
  esac
done
if ((dirs > 1)); then
  usage
fi
cd -- "$dir"

set -x
"$devenv/copy/common/bin/sh-tools.sh" "$mode"
ruff=(uv run --project "$devenv" --group lint ruff)
if [[ $mode == --fix ]]; then
  # What ruff cannot fix is listed but does not stop the format; --lint fails.
  "${ruff[@]}" check --fix --exit-zero .
  "${ruff[@]}" format .
else
  "${ruff[@]}" check .
  "${ruff[@]}" format --check .
fi
