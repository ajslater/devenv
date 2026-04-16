#!/usr/bin/env python3
"""
Merge development environment dotfiles.

For each enabled DEVENV_<FEATURE>, merges .*ignore and .*rc files from
templates/<feature>/ into the destination directory by deduplicating and
sorting lines. Skips symlinks.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _devenv_common import (
    git_status,
    iter_feature_dirs,
    report_counts,
)


def _is_dotfile(name: str) -> bool:
    return name.startswith(".") and name.endswith(("ignore", "rc"))


def merge_dotfiles(
    templates_dir: Path, dest: Path, features: list[str] | None = None
) -> tuple[int, int, int, list[Path]]:
    """
    Merge dotfiles from templates/<feature>/ into dest.

    Returns (created_count, skipped_count, merged_count, list_of_dest_files).
    """
    created = 0
    skipped = 0
    merged = 0
    dest_files: list[Path] = []

    for _feature, feature_dir in iter_feature_dirs(templates_dir, features):
        for src_file in sorted(feature_dir.iterdir()):
            if not src_file.is_file() or not _is_dotfile(src_file.name):
                continue

            dest_file = dest / src_file.name
            if not dest_file.exists():
                dest_file.touch()
                created += 1

            if dest_file.is_symlink():
                skipped += 1
                continue

            src_lines = set(src_file.read_text().splitlines())
            existing_lines = set(dest_file.read_text().splitlines())
            merged_lines = sorted(src_lines | existing_lines)
            dest_file.write_text("\n".join(merged_lines) + "\n" if merged_lines else "")
            dest_files.append(dest_file)
            merged += 1

    return created, skipped, merged, dest_files


def main() -> None:
    """CLI entry point for merge_dotfiles."""
    parser = argparse.ArgumentParser(
        description="Merge devenv dotfiles into target project"
    )
    parser.add_argument("templates_dir", type=Path, help="Templates source directory")
    parser.add_argument("dest", type=Path, help="Destination project directory")
    args = parser.parse_args()

    created, skipped, merged, dest_files = merge_dotfiles(args.templates_dir, args.dest)
    report_counts("Merged dotfiles", created=created, skipped=skipped, merged=merged)
    git_status(dest_files)


if __name__ == "__main__":
    main()
