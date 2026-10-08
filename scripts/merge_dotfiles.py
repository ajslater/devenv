#!/usr/bin/env python3
"""
Merge development environment dotfiles.

For each enabled DEVENV_<FEATURE>, merges .*ignore and .*rc files from
merge/<feature>/ into the destination directory by deduplicating and
sorting lines, with "!" negations after every other line. Lines listed in
remove_dotfile_lines.txt are retired: they are dropped from every merged file.
An ignore file also drops each pattern that another of its patterns already
covers, such as "dist/" beside "dist". Skips symlinks.
"""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from _devenv_common import (  # pyright: ignore[reportImplicitRelativeImport]
    get_devenv_src,
    git_status,
    iter_feature_dirs,
    report_counts,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

RETIRED_LINES_FILE = "remove_dotfile_lines.txt"
NO_RETIRED_LINES: frozenset[str] = frozenset()
_GLOB_CHARS = frozenset("*?[\\")


class _Pattern(NamedTuple):
    """An ignore pattern reduced to what decides the paths it matches."""

    name: str  # the pattern without its anchor or trailing slash
    any_depth: bool  # matches below the root, not only at it
    dir_only: bool  # matches only directories


def _gitignore_pattern(line: str) -> _Pattern:
    """
    Read a .gitignore line. prettier and bin/roman.py read the same syntax.

    A pattern led by "**/", or with no slash before its end, matches at any
    depth. A leading or inner slash anchors it to the root. A trailing slash
    matches only directories.
    """
    dir_only = line.endswith("/")
    body = line.removesuffix("/")
    if body.startswith("**/"):
        return _Pattern(body[3:], any_depth=True, dir_only=dir_only)
    if body.startswith("/"):
        return _Pattern(body[1:], any_depth=False, dir_only=dir_only)
    return _Pattern(body, any_depth="/" not in body, dir_only=dir_only)


def _dockerignore_pattern(line: str) -> _Pattern:
    """
    Read a .dockerignore line.

    Docker anchors every pattern to the context root and disregards leading
    and trailing slashes. A leading "**/" matches at any depth, root included.
    """
    body = line.strip("/").removeprefix("./")
    if body.startswith("**/"):
        return _Pattern(body[3:], any_depth=True, dir_only=False)
    return _Pattern(body, any_depth=False, dir_only=False)


def _shellignore_pattern(line: str) -> _Pattern:
    """
    Read a .shellignore line as bin/find-sh.sh does.

    It strips a leading ./ or / and a trailing /. Then a pattern without a
    slash matches a name at any depth, and one with a slash is a path from
    the root.
    """
    body = line.removeprefix("./").removeprefix("/").removesuffix("/")
    return _Pattern(body, any_depth="/" not in body, dir_only=False)


_READERS: MappingProxyType[str, Callable[[str], _Pattern]] = MappingProxyType(
    {
        ".dockerignore": _dockerignore_pattern,
        ".shellignore": _shellignore_pattern,
    }
)


def _covers(wide: _Pattern, narrow: _Pattern) -> bool:
    """Return whether wide matches every path narrow matches."""
    if (wide.dir_only and not narrow.dir_only) or (
        narrow.any_depth and not wide.any_depth
    ):
        return False
    if wide.name == narrow.name:
        return True
    # A plain name inside a one-component glob, as ".mypy_cache" is in ".*cache".
    return (
        "/" not in wide.name + narrow.name
        and "\\" not in wide.name
        and not _GLOB_CHARS & set(narrow.name)
        and fnmatchcase(narrow.name, wide.name)
    )


def prune_covered(file_name: str, lines: Iterable[str]) -> set[str]:
    """
    Drop each line of an ignore file that another of its lines covers.

    Of two lines that match the same paths, such as "foo" and "**/foo" in a
    .gitignore, the shorter stays. A file with a "!" line is left whole: the
    merge sorts lines, and a negation's effect depends on where it falls.
    """
    kept = set(lines)
    if not file_name.endswith("ignore") or any(line.startswith("!") for line in kept):
        return kept
    read = _READERS.get(file_name, _gitignore_pattern)
    patterns = {
        line: pattern
        for line in kept
        if line == line.strip()
        and not line.startswith("#")
        and (pattern := read(line)).name
    }

    def covered(line: str, pattern: _Pattern) -> bool:
        return any(
            _covers(other_pattern, pattern)
            and (
                not _covers(pattern, other_pattern)
                or (len(other), other) < (len(line), line)
            )
            for other, other_pattern in patterns.items()
            if other != line
        )

    return kept - {line for line, pattern in patterns.items() if covered(line, pattern)}


def _negations_last(line: str) -> tuple[bool, str]:
    """
    Sort key that puts each "!" line after every other line.

    git, docker and prettier let the last matching line win, so a negation
    only works after the patterns it overrides. Within each group the order
    does not matter, since every pattern ignores and every negation keeps.
    """
    return line.startswith("!"), line


def _is_dotfile(name: str) -> bool:
    return name.startswith(".") and name.endswith(("ignore", "rc"))


def read_retired_lines(devenv_src: Path) -> frozenset[str]:
    """Return the dotfile lines devenv has retired, one per non-blank line."""
    path = devenv_src / RETIRED_LINES_FILE
    if not path.exists():
        return frozenset()
    return frozenset(line for line in path.read_text().splitlines() if line.strip())


def _iter_template_dotfiles(
    templates_dir: Path, features: list[str] | None
) -> Generator[Path]:
    """Yield the dotfiles in merge/<feature>/ for each enabled feature."""
    for _feature, feature_dir in iter_feature_dirs(templates_dir, features):
        for src_file in sorted(feature_dir.iterdir()):
            if src_file.is_file() and _is_dotfile(src_file.name):
                yield src_file


def merge_dotfiles(
    templates_dir: Path,
    dest: Path,
    features: list[str] | None = None,
    retired_lines: frozenset[str] = NO_RETIRED_LINES,
) -> tuple[int, int, int, list[Path]]:
    """
    Merge dotfiles from merge/<feature>/ into dest, dropping retired lines.

    Returns (created_count, skipped_count, merged_count, list_of_dest_files).
    """
    created = 0
    skipped = 0
    merged = 0
    dest_files: list[Path] = []

    for src_file in _iter_template_dotfiles(templates_dir, features):
        dest_file = dest / src_file.name
        if not dest_file.exists():
            dest_file.touch()
            created += 1

        if dest_file.is_symlink():
            skipped += 1
            continue

        src_lines = set(src_file.read_text().splitlines())
        existing_lines = set(dest_file.read_text().splitlines())
        merged_lines = sorted(
            prune_covered(dest_file.name, (src_lines | existing_lines) - retired_lines),
            key=_negations_last,
        )
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

    created, skipped, merged, dest_files = merge_dotfiles(
        args.templates_dir,
        args.dest,
        retired_lines=read_retired_lines(get_devenv_src()),
    )
    report_counts("Merged dotfiles", created=created, skipped=skipped, merged=merged)
    git_status(dest_files)


if __name__ == "__main__":
    main()
