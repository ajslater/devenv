#!/usr/bin/env bash
# Delete all files listed in the delete.txt file
# Requires DEVENV_SRC usually set in makefiles
set -euo pipefail
DELETE_FILE=$DEVENV_SRC/remove_files.txt
existing_files=()
while IFS= read -r file || [[ -n "$file" ]]; do
  [[ -z "$file" || "$file" == \#* ]] && continue
  [[ -f "$file" ]] && existing_files+=("$file")
done < "$DELETE_FILE"

if ((${#existing_files[@]})); then
  echo "Deleting ${#existing_files[@]} files..."
  rm -f -- "${existing_files[@]}"
fi
