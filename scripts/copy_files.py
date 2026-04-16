#!/usr/bin/env python3
"""
Copy files from devenv root/<feature>/ directories to a target project.

For each enabled DEVENV_<FEATURE>, recursively copies all files from
root/<feature>/ into the target directory, preserving relative paths.
Skips backup files (*~) and files identical to the destination.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

from _devenv_common import (
    get_devenv_src,
    git_status,
    iter_feature_dirs,
    report_counts,
)


def copy_files(
    root_dir: Path, dest: Path, features: list[str] | None = None
) -> tuple[int, int, list[Path]]:
    """
    Copy files from root/<feature>/ to dest, preserving relative paths.

    Returns (copied_count, skipped_count, list_of_dest_files).
    """
    copied = 0
    skipped = 0
    dest_files: list[Path] = []

    for _feature, feature_dir in iter_feature_dirs(root_dir, features):
        for src_file in sorted(feature_dir.rglob("*")):
            if not src_file.is_file() or src_file.name.endswith("~"):
                continue
            rel = src_file.relative_to(feature_dir)
            dest_file = dest / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            if dest_file.exists() and filecmp.cmp(src_file, dest_file, shallow=False):
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
        help="Root source directory (default: DEVENV_SRC/root)",
    )
    args = parser.parse_args()

    root_dir = args.root or get_devenv_src() / "root"
    copied, skipped, dest_files = copy_files(root_dir, args.dest)
    report_counts("Copied files", copied=copied, skipped=skipped)
    git_status(dest_files)


if __name__ == "__main__":
    main()
