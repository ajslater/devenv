#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "mbake~=1.4.5",
#   "packaging>=26.0",
#   "pyyaml~=6.0",
#   "semver~=3.1",
#   "tomlkit~=0.14",
# ]
# ///
"""
Update a project by merging devenv templates and copying feature files.

Main orchestrator that:
1. Deletes obsolete files listed in remove_files.txt
2. Merges dotfiles from merge/<feature>/
3. Copies files from copy/<feature>/
4. Merges config files (package.json, YAML, TOML)
5. Runs formatters on merged files

Run it with `make update-devenv`, which sets the DEVENV_<FEATURE> flags from
the cfg/*.mk files the project Makefile includes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import merge_package_json  # ty: ignore[unresolved-import]
import merge_toml  # ty: ignore[unresolved-import]
import merge_yaml  # ty: ignore[unresolved-import]
from _devenv_common import (  # ty: ignore[unresolved-import]
    exit_on_unmet_requirements,
    get_devenv_src,
    get_enabled_features,
    git_status,
    missing_tools,
    read_lines,
    report_counts,
    run,
)
from _makefiles import format_makefiles  # ty: ignore[unresolved-import]
from copy_files import copy_files  # ty: ignore[unresolved-import]
from merge_dotfiles import (  # ty: ignore[unresolved-import]
    merge_dotfiles,
    read_retired_lines,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

NO_FEATURES = (
    "devenv: no DEVENV_<FEATURE> flags are set. Run `make update-devenv`, "
    "which sets them from the cfg/*.mk files the Makefile includes."
)
NODE_TOOLS = ("bun", "bunx")


def delete_files(devenv_src: Path) -> None:
    """Delete the files listed in remove_files.txt, naming each one."""
    for entry in read_lines(devenv_src / "remove_files.txt"):
        path = Path(entry)
        if path.is_file():
            path.unlink()
            print(f"Deleted retired {path}")  # noqa: T201


@dataclass(frozen=True, slots=True)
class ConfigMerge:
    """A config file that devenv merges into the project."""

    feature: str  # the feature that owns the file
    merger: Callable[[Sequence[str]], None]  # a merger module's CLI main
    template: str  # file name under merge/<feature>/
    output: str  # file name in the project
    # (flag, path under devenv) pairs, passed when devenv ships the path
    options: tuple[tuple[str, str], ...] = ()


CONFIG_MERGES: Final = (
    ConfigMerge(
        "node_root",
        merge_package_json.main,
        "package.json",
        "package.json",
        (
            ("--remove", "remove_node_packages.txt"),
            ("--remove-values", "merge/node_root/package-remove.json"),
        ),
    ),
    ConfigMerge("docs", merge_yaml.main, ".readthedocs.yaml", ".readthedocs.yaml"),
    ConfigMerge("docs", merge_yaml.main, "mkdocs.yml", "mkdocs.yml"),
    ConfigMerge(
        "python",
        merge_toml.main,
        "pyproject-template.toml",
        "pyproject.toml",
        (("--remove-values", "merge/python/pyproject-remove.toml"),),
    ),
    ConfigMerge("ci", merge_yaml.main, "compose.yaml", "compose.yaml"),
)


def merge_config(
    devenv_src: Path, pd: Path, features: list[str], merge: ConfigMerge
) -> Path | None:
    """
    Merge one config file with its merger's CLI, in process.

    The owning feature's template goes first, then the same template from
    any other enabled feature (django adds djlint to pyproject.toml), then
    the project's own file, so its values win. Returns the output if merged.
    """
    owners = [merge.feature, *(f for f in features if f != merge.feature)]
    sources = [
        path
        for feature in owners
        if (path := devenv_src / "merge" / feature / merge.template).is_file()
    ]
    if not sources:
        return None
    output = pd / merge.output
    if output.is_file():
        sources.append(output)
    options = [
        arg
        for flag, rel in merge.options
        if (devenv_src / rel).is_file()
        for arg in (flag, str(devenv_src / rel))
    ]
    merge.merger([*map(str, sources), "-o", str(output), *options])
    return output


def merge_configs(devenv_src: Path, pd: Path, features: list[str]) -> list[Path]:
    """Merge each enabled feature's config templates into the project."""
    return [
        output
        for merge in CONFIG_MERGES
        if merge.feature in features
        and (output := merge_config(devenv_src, pd, features, merge))
    ]


def format_merged(merged: list[Path]) -> None:
    """Install merged node dependencies and format the merged files."""
    if not merged:
        return
    if not Path("package.json").is_file():
        print("Not formatting merged files: no package.json for eslint and prettier.")  # noqa: T201
        return
    # `bun install` syncs the lockfile with whatever the merge added or
    # changed, but leaves the merged specs alone.
    run(["bun", "install"])
    names = [str(path.name) for path in merged]
    eslint = subprocess.run(  # noqa: S603
        ["bunx", "eslint", "--cache", "--fix", *names],  # noqa: S607
        check=False,
    )
    if eslint.returncode:
        print(  # noqa: T201
            "devenv: eslint could not fix everything above; continuing.",
            file=sys.stderr,
        )
    run(["bunx", "prettier", "--write", *names])


def main(*, update_deps: bool = True) -> None:
    """Run the full devenv update pipeline."""
    devenv_src = get_devenv_src()
    pd = Path.cwd()
    features = get_enabled_features()
    if not features:
        sys.exit(NO_FEATURES)
    exit_on_unmet_requirements(features)
    uses_node = "node_root" in features or (pd / "package.json").is_file()
    if uses_node and (missing := missing_tools(NODE_TOOLS)):
        sys.exit(f"devenv: install {' and '.join(missing)} first: brew install bun")

    delete_files(devenv_src)

    created, skipped, merged, _dotfile_paths = merge_dotfiles(
        devenv_src / "merge", pd, features, read_retired_lines(devenv_src)
    )
    report_counts("Merged dotfiles", created=created, skipped=skipped, merged=merged)

    copied, file_skipped, _copied_paths = copy_files(devenv_src / "copy", pd, features)
    report_counts("Copied files", copied=copied, skipped=file_skipped)

    # Sort ignore files with the sort-ignore.sh just copied, not the
    # project's old one.
    if (pd / "bin" / "sort-ignore.sh").is_file():
        run(["bin/sort-ignore.sh"])
    format_makefiles()

    # Refresh node dependency versions before merging. `bun update` rewrites
    # every spec to a caret range, so running it after the merge would clobber
    # the deliberately unbounded (>=) ranges the template reasserts.
    if update_deps and (pd / "package.json").is_file():
        run(["bun", "update"])

    merged_files = merge_configs(devenv_src, pd, features)
    format_merged(merged_files)
    git_status([".*", "bin", "cfg", *merged_files])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update project with devenv templates and feature files"
    )
    parser.add_argument(
        "--no-update-deps",
        action="store_true",
        help="Keep node dependency versions instead of running `bun update`",
    )
    args = parser.parse_args()
    main(update_deps=not args.no_update_deps)
