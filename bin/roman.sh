#!/usr/bin/env bash
# Find all shell scripts without a second line comment.
# Detects shell scripts by shebang.
# Inspired by @defunctzombie
set -euo pipefail

# Shells recognised as "shell scripts" when found in a shebang line.
# Extend this list to taste.
SHELL_SHEBANG_PATTERN='^#!.*(bash|sh|zsh|ksh|dash|csh|tcsh|fish)'

# ---------------------------------------------------------------------------
# Options & usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: $0 [options] <path> [path...]"
  echo "Options:"
  echo -e "\t-i <ignorefile>"
  exit 1
}

ignorefile=""
while getopts ":i:" opt; do
  case $opt in
  i) ignorefile=$OPTARG ;;
  :)
    echo "Error: -${OPTARG} requires an argument"
    usage
    ;;
  ?)
    echo "Error: unknown option -${OPTARG}"
    usage
    ;;
  esac
done
shift $((OPTIND - 1))

[ "${1:-}" = "" ] && usage

# ---------------------------------------------------------------------------
# Build grep command
# ---------------------------------------------------------------------------
# Pick the best available grep-compatible command
if command -v rg &>/dev/null; then
  GREP_TOOL="rg"
elif command -v ggrep &>/dev/null; then
  GREP_TOOL="ggrep"
else
  GREP_TOOL="grep"
fi

# Wrapper so callers can always pass -E: rg uses ERE by default and errors
# if given -E, so we strip it for rg while passing it through for grep/ggrep.
run_grep() {
  if [ "$GREP_TOOL" = "rg" ]; then
    local args=()
    for arg in "$@"; do
      [ "$arg" != "-E" ] && args+=("$arg")
    done
    rg "${args[@]}"
  else
    "$GREP_TOOL" "$@"
  fi
}

# ---------------------------------------------------------------------------
# Build find command
# ---------------------------------------------------------------------------
HIDDEN_PATTERN='.*'
BACKUP_PATTERN='*~'
find_cmd=(find "$@" \( -name "$HIDDEN_PATTERN" -prune \) -o \( -type f ! -name "$BACKUP_PATTERN" -print \))
if [ "${ignorefile:-}" != "" ]; then
  while IFS= read -r pattern; do
    find_cmd+=(! -name "$pattern")
  done <"$ignorefile"
fi

# ---------------------------------------------------------------------------
# Iterate over files and check for zombie compliance
# ---------------------------------------------------------------------------
good=1
while IFS= read -r f; do
  echo "$f"
  head_lines=$(head -2 "$f")
  line1=$(echo "$head_lines" | awk 'NR==1')
  line2=$(echo "$head_lines" | awk 'NR==2')

  # Skip files that don't have a shell shebang on line 1
  echo "$line1" | run_grep -q -E "$SHELL_SHEBANG_PATTERN" || continue

  # Flag files missing a comment on line 2
  if ! echo "$line2" | run_grep -q '^# '; then
    echo "🔪 $f"
    good=0
  fi
done < <("${find_cmd[@]}")

if [ "$good" = 0 ]; then
  exit 1
fi
echo 👍
