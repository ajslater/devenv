#!/usr/bin/env bash
# Fix django template lint errors
set -euxo pipefail

mapfile -t templates < <(find . -path '*/templates/*' -name '*.html')
if [ ${#templates[@]} -eq 0 ]; then
  echo "No django template files found. Nothing fixed."
  exit 0
fi
uv run --group lint djlint --reformat "${templates[@]}"
