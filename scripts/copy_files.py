#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""
Copy files from devenv copy/<feature>/ directories to a target project.

For each enabled DEVENV_<FEATURE>, recursively copies all files from
copy/<feature>/ into the target directory, preserving relative paths.
Skips backup files (*~), .DS_Store, __pycache__ and files identical to the
destination. A file named
like eslint.config.init.js is installed without its ".init", so a starter
does not act as a config inside devenv itself.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

from _devenv_common import (  # ty: ignore[unresolved-import]
    get_devenv_src,
    git_status,
    iter_feature_dirs,
    report_counts,
)

# Editor backups and OS or interpreter droppings in a devenv checkout.
SKIP_NAMES = frozenset({".DS_Store"})
SKIP_DIRS = frozenset({"__pycache__"})


def _is_shipped(src_rel: Path) -> bool:
    return not (
        src_rel.name.endswith("~")
        or src_rel.name in SKIP_NAMES
        or SKIP_DIRS.intersection(src_rel.parts)
    )


def _dest_rel(src_rel: Path) -> Path:
    return src_rel.with_name(src_rel.name.replace(".init.", ".", 1))


def copy_files(
    root_dir: Path,
    dest: Path,
    features: list[str] | None = None,
    *,
    clobber: bool = True,
) -> tuple[int, int, list[Path]]:
    """
    Copy files from <root_dir>/<feature>/ to dest, preserving relative paths.

    With clobber=False an existing file is never replaced, which is how
    starter files from init/ are installed.

    Returns (copied_count, skipped_count, list_of_dest_files).
    """
    copied = 0
    skipped = 0
    dest_files: list[Path] = []

    for _feature, feature_dir in iter_feature_dirs(root_dir, features):
        for src_file in sorted(feature_dir.rglob("*")):
            src_rel = src_file.relative_to(feature_dir)
            if not src_file.is_file() or not _is_shipped(src_rel):
                continue
            dest_file = dest / _dest_rel(src_rel)
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            if dest_file.exists() and (
                not clobber or filecmp.cmp(src_file, dest_file, shallow=False)
            ):
                skipped += 1
            else:
                shutil.copy2(src_file, dest_file)
                copied += 1
            dest_files.append(dest_file)

    return copied, skipped, dest_files


def main() -> None:
    """CLI entry point for copy_files."""
    parser = argparse.ArgumentParser(
        description="Copy devenv root files to target project"
    )
    parser.add_argument("dest", type=Path, help="Destination project directory")
    parser.add_argument(
        "--root",
        type=Path,
        help="Root source directory (default: DEVENV_SRC/copy)",
    )
    parser.add_argument(
        "--no-clobber",
        action="store_true",
        help="Never replace a file that already exists",
    )
    args = parser.parse_args()

    root_dir = args.root or get_devenv_src() / "copy"
    copied, skipped, dest_files = copy_files(
        root_dir, args.dest, clobber=not args.no_clobber
    )
    report_counts("Copied files", copied=copied, skipped=skipped)
    git_status(dest_files)


if __name__ == "__main__":
    main()
