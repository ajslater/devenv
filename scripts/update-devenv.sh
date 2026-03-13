#!/usr/bin/env bash
# Update a project by merging the devenv templates
# Requires DEVENV_<FEATURE> variables set in makefiles
set -euo pipefail

########
# Init #
########
DEVENV_SRC=${DENENV_SRC:-$(realpath "$(dirname "$0")/..")}
PD=$PWD

"$DEVENV_SRC"/scripts/delete-files.sh
mkdir -pv "$PD"/bin "$PWD"/cfg

##########
# Update #
##########

# Dotfiles
"$DEVENV_SRC"/scripts/merge-dotfiles.sh "$DEVENV_SRC/templates" "$PD"
bin/sort-ignore.sh

# Scripts
SUBDIRS=(bin cfg)
for d in "${SUBDIRS[@]}"; do
  "$DEVENV_SRC"/scripts/copy-new-files.sh "$DEVENV_SRC/$d" "$PD/$d"
done
uv run mbake format Makefile cfg/*.mk
shellharden --replace bin/*.sh

fix_files=()
# Common: Javascript
if [ "${DEVENV_NODE:-}" != "" ]; then
  f=package.json
  template_f="$DEVENV_SRC/templates/node/$f"
  output_f="$PD/$f"
  uv run "$DEVENV_SRC"/scripts/merge_package_json.py "$template_f" "$output_f" -o "$output_f" --remove "$DEVENV_SRC/remove_node_packages.txt"
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
  npm update

  # Fix after merge
  npx eslint --cache --fix "${fix_files[@]}"
  npx prettier --write "${fix_files[@]}"

  # Report
  git status --short .* bin cfg "${fix_files[@]}"
fi
