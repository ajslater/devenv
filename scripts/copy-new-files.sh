#!/usr/bin/env bash
# Usage: ./copy-new-files.sh SOURCE_DIR DEST_DIR
# Requires feature variables set by parse-config.sh
set -euo pipefail

SOURCE_DIR="${1:?Source directory required}"
DEST_DIR="${2:?Destination directory required}"

# Verify source directory exists
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Error: Source directory '$SOURCE_DIR' does not exist"
  exit 1
fi

# Create destination directory if it doesn't exist
mkdir -p "$DEST_DIR"

# Counter for copied files
copied=0
skipped=0
dest_files=()

function copy_files() {
  local SOURCE_SUBDIR=$1
  # Iterate through all files in source directory
  while read -r src_file; do
    # Get relative path from source directory
    local rel_path="${src_file#"$SOURCE_SUBDIR/"}"
    local dest_file="$DEST_DIR/$rel_path"

    # Check if destination file exists and compare contents
    if [[ -f "$dest_file" ]] && cmp -s "$src_file" "$dest_file"; then
      # echo "Skipping (identical): $rel_path"
      ((skipped++)) || true
    else
      # echo "Copying: $rel_path"
      cp -a "$src_file" "$dest_file"
      ((copied++)) || true
    fi
    dest_files+=("$dest_file")
  done < <(find "$SOURCE_SUBDIR" -type f ! -name '*~')
}

FEATURES=(common docker ci python docs frontend django)
for feature in "${FEATURES[@]}"; do
  varname="DEVENV_${feature^^}"
  if [ "${!varname:-}" ]; then
    subdir="$SOURCE_DIR/$feature"
    if [ -d "$subdir" ]; then
      copy_files "$subdir" "$DEST_DIR"
    fi
  fi
done

if ((copied)) || ((skipped)); then
  echo -n "Copied files:"
  if ((copied)); then
    echo " $copied copied"
  fi
  if ((skipped)); then
    echo " $skipped skipped"
  fi
  echo ""
  git status --short "${dest_files[@]}"
fi
