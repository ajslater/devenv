#!/usr/bin/env bash
# Update a project by merging the devenv templates
# Requires variables set by parse-config.sh
set -euo pipefail

########
# Init #
########
DEVENV_SRC="${1:-${DEVENV_SRC:-}}"
[ "${DEVENV_SRC:-}" == "" ] && DEVENV_SRC=../devenv
PD=$PWD

source "$DEVENV_SRC/scripts/parse-config.sh"

"$DEVENV_SRC"/scripts/delete-files.sh "$DEVENV_SRC"
mkdir -pv "$PD"/bin "$PWD"/cfg

##########
# Update #
##########

# Dotfiles
"$DEVENV_SRC"/scripts/merge-dotfiles.sh "$DEVENV_SRC/templates" "$PD"

# Scripts
SUBDIRS=(bin cfg)
for d in "${SUBDIRS[@]}"; do
  "$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC/$d" "$PD/$d"
done

fix_files=()
# Common: Javascript
if [ "${DEVENV_COMMON:-}" != "" ]; then
  f=package.json
  template_f="$DEVENV_SRC/templates/common/$f"
  output_f="$PD/$f"
  uv run "$DEVENV_SRC"/scripts/merge_package_json.py "$template_f" "$output_f" -o "$output_f"
  fix_files+=("$f")
fi

# Docs
if [ "${DEVENV_DOCS:-}" != "" ]; then
  DOCFNS=(.readthedocs.yaml mkdocs.yml)
  for f in "${DOCFNS[@]}"; do
    template_f="$DEVENV_SRC/templates/docs/$f"
    output_f="$PD/$f"
    uv run "$DEVENV_SRC"/scripts/merge_yaml.py "$template_f" "$output_f" -o "$output_f"
    fix_files+=("$f")
  done
fi

# Python
if [ "${DEVENV_PYTHON:-}" != "" ]; then
  f=pyproject.toml
  output_f="$PD/$f"
  template_f="$DEVENV_SRC/templates/python/pyproject-template.toml"
  uv run "$DEVENV_SRC"/scripts/merge_toml.py "$template_f" "$output_f" -o "$output_f"
  fix_files+=("$f")
fi

##########
# Finish #
##########

# Fix Merged
if ((${#fix_files[@]})); then
  # npm update

  # Fix
  npx eslint_d --cache --fix "${fix_files[@]}"
  npx prettier --write "${fix_files[@]}"

  # Report
  git status --short "${fix_files[@]}"
fi
