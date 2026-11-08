#!/usr/bin/env python3
# /// script
# requires-python = ">=3.15"
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

delete_disabled_files undoes a copy for the features a project does not
enable, deleting only files that still hold devenv's bytes.
"""

import argparse
import filecmp
from pathlib import Path
lazy from collections.abc import Iterator

from _devenv_common import (
    FEATURES,
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


def _shipped_files(feature_dir: Path) -> Iterator[tuple[Path, Path]]:
    """Yield (source file, path in the project) for each file feature_dir ships."""
    for src_file in sorted(feature_dir.rglob("*")):
        src_rel = src_file.relative_to(feature_dir)
        if src_file.is_file() and _is_shipped(src_rel):
            yield src_file, _dest_rel(src_rel)


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
        for src_file, dest_rel in _shipped_files(feature_dir):
            dest_file = dest / dest_rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            if dest_file.exists() and (
                not clobber or filecmp.cmp(src_file, dest_file, shallow=False)
            ):
                skipped += 1
            else:
                src_file.copy(dest_file, preserve_metadata=True)
                copied += 1
            dest_files.append(dest_file)

    return copied, skipped, dest_files


def _is_devenv_copy(src_file: Path, dest_file: Path) -> bool:
    """Return whether dest_file is a plain file holding src_file's bytes."""
    return (
        dest_file.is_file()
        and not dest_file.is_symlink()
        and filecmp.cmp(src_file, dest_file, shallow=False)
    )


def _disabled_copies(
    root_dir: Path, dest: Path, features: list[str]
) -> Iterator[tuple[str, Path]]:
    """
    Yield (feature, path in dest) for each devenv copy of a disabled feature.

    A path an enabled feature also ships is never yielded. Each path is
    checked only when reached, so one that two disabled features ship and
    the caller has already deleted is not yielded again.
    """
    enabled = {
        dest_rel
        for _feature, feature_dir in iter_feature_dirs(root_dir, features)
        for _src, dest_rel in _shipped_files(feature_dir)
    }
    disabled = [feature for feature in FEATURES if feature not in features]
    for feature, feature_dir in iter_feature_dirs(root_dir, disabled):
        for src_file, dest_rel in _shipped_files(feature_dir):
            if dest_rel not in enabled and _is_devenv_copy(src_file, dest / dest_rel):
                yield feature, dest_rel


def _remove_empty_dirs(dest: Path, rel_dirs: set[Path]) -> None:
    """Remove each of rel_dirs under dest that is empty, deepest first."""
    for rel_dir in sorted(rel_dirs, key=lambda path: len(path.parts), reverse=True):
        if not any((dest / rel_dir).iterdir()):
            (dest / rel_dir).rmdir()


def delete_disabled_files(root_dir: Path, dest: Path, features: list[str]) -> None:
    """
    Delete what <root_dir>/<feature>/ ships for each feature dest does not enable.

    Only a file identical to devenv's source goes, so one the project changed
    stays, and so does a path an enabled feature also ships. Each deletion is
    printed. A directory goes only when these deletions leave it empty.
    """
    parents: set[Path] = set()
    for feature, dest_rel in _disabled_copies(root_dir, dest, features):
        (dest / dest_rel).unlink()
        print(f"Deleted {dest_rel}: feature {feature} is off")  # noqa: T201
        parents.update(dest_rel.parents[:-1])
    _remove_empty_dirs(dest, parents)


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
