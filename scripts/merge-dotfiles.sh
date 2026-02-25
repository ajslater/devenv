#!/usr/bin/env bash
# Merge development environment dotfiles
# Requires variables set by parse-config.sh
set -euo pipefail
SRC=$1
DEST=$2

created=0
skipped=0
merged=0
dest_files=()

function merge_files() {
  local SRC_SUBDIR=$1
  shopt -s nullglob
  files=("$SRC_SUBDIR"/.*ignore "$SRC_SUBDIR"/.*rc)
  shopt -u nullglob
  for src_f in "${files[@]}"; do
    dest_f=$DEST/$(basename "$src_f")
    if [ ! -f "$dest_f" ]; then
      touch "$dest_f"
      ((created++)) || true
    fi
    if [ -L "$dest_f" ]; then
      ((skipped++)) || true
    else
      sort --mmap --unique --output="$dest_f" "$src_f" "$dest_f"
      dest_files+=("$dest_f")
      ((merged++)) || true
    fi
  done
}

FEATURES=(common docker ci python docs frontend django)
for feature in "${FEATURES[@]}"; do
  varname="DEVENV_${feature^^}"
  if [ "${!varname:-}" ]; then
    subdir="$SRC/$feature"
    if [ -d "$subdir" ]; then
      merge_files "$subdir" "$DEST"
    fi
  fi
done

if ((created)) || ((skipped)) || ((merged)); then
  echo -n "Merged dotfiles:"
  if ((created)); then
    echo -n " $created created"
  fi
  if ((skipped)); then
    echo -n " $skipped skipped"
  fi
  if ((merged)); then
    echo -n " $merged merged"
  fi
  echo ""
  git status --short "${dest_files[@]}"
fi
