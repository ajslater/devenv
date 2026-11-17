#!/usr/bin/env python3
# /// script
# requires-python = ">=3.15"
# ///
"""
Run `make update-devenv` in every devenv project beside this checkout.

The projects are the directories beside devenv's main checkout whose Makefile
includes cfg/common.mk, which defines update-devenv. Run from a worktree, it
still looks beside the main checkout, and updates them from the worktree.

--update and --fix follow with `make update` and `make fix`, each skipped where
the project has no such target. A project with uncommitted changes is skipped
unless --dirty is given, so devenv's changes never mix with work in progress.
A failed step stops that project only, and the summary at the end says how
each project went.
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    lazy from collections.abc import Mapping, Sequence

from _devenv_common import get_devenv_src

_COMMON_INCLUDE_RE: Final = re.compile(r"^include\s+cfg/common\.mk\s*$", re.MULTILINE)
_NO_RULE: Final = "No rule to make target"
_INTERRUPTED: Final = 130


class Status(StrEnum):
    """How a project's update went."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "would run"


@dataclass(frozen=True, slots=True)
class GitState:
    """A project's branch and how many files git reports changed."""

    branch: str
    changed: int


@dataclass(slots=True)
class Result:
    """One line of the summary."""

    project: Path
    branch: str
    status: Status = Status.OK
    notes: list[str] = field(default_factory=list)


def code_root(devenv_src: Path) -> Path:
    """Return the directory that holds devenv's main checkout and its projects."""
    if (devenv_src / ".git").exists():
        git_dir = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
            cwd=devenv_src,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(git_dir).parent.parent
    return devenv_src.parent


def find_projects(root: Path) -> list[Path]:
    """Return the directories in root whose Makefile includes cfg/common.mk."""
    return sorted(
        path
        for path in root.iterdir()
        if (makefile := path / "Makefile").is_file()
        and _COMMON_INCLUDE_RE.search(makefile.read_text(errors="replace"))
        # Other devenv checkouts include it too, but update from themselves.
        and not (path / "scripts" / "update_devenv.py").is_file()
    )


def git_state(project: Path) -> GitState:
    """Read the project's branch and its changed and untracked file count."""
    lines = subprocess.run(
        ["git", "status", "--porcelain=v2", "--branch"],  # noqa: S607
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    branch = next(
        (line.split()[2] for line in lines if line.startswith("# branch.head ")), ""
    )
    return GitState(branch, sum(not line.startswith("#") for line in lines))


def child_env(devenv_src: Path) -> dict[str, str]:
    """
    Return the environment each project's make runs in.

    `uv run` points VIRTUAL_ENV at this script's environment, which every
    project's own uv would warn about and then ignore. A DEVENV_<FEATURE>
    flag left in the environment would switch that feature on in every
    project, whatever its Makefile includes.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "VIRTUAL_ENV" and not key.startswith("DEVENV_")
    }
    env["DEVENV_SRC"] = str(devenv_src)
    return env


def _make(
    project: Path, args: Sequence[str], env: Mapping[str, str], *, quiet: bool = False
) -> subprocess.CompletedProcess[str]:
    # On the command line too: the starter Makefile sets DEVENV_SRC with :=,
    # which overrides the environment.
    return subprocess.run(  # noqa: S603
        ["make", *args, f"DEVENV_SRC={env['DEVENV_SRC']}"],  # noqa: S607
        cwd=project,
        env=env,
        capture_output=quiet,
        text=True,
        check=False,
    )


def has_target(project: Path, target: str, env: Mapping[str, str]) -> bool:
    """Whether the project's make knows target. `make -q` runs no recipe."""
    return _NO_RULE not in _make(project, ["-q", target], env, quiet=True).stderr


def run_steps(
    project: Path,
    steps: Sequence[Sequence[str]],
    env: Mapping[str, str],
    *,
    dry_run: bool,
) -> tuple[Status, list[str]]:
    """Run each make command in project until one fails."""
    notes: list[str] = []
    for index, step in enumerate(steps):
        target = step[0]
        # update-devenv comes from cfg/common.mk, which every project includes.
        if index and not has_target(project, target, env):
            notes.append(f"no {target} target")
        elif not dry_run:
            print(f"--- make {' '.join(step)}", flush=True)  # noqa: T201
            if _make(project, step, env).returncode:
                return Status.FAILED, [*notes, f"make {target} failed"]
    return Status.PENDING if dry_run else Status.OK, notes


def update(
    project: Path,
    steps: Sequence[Sequence[str]],
    env: Mapping[str, str],
    *,
    dirty: bool,
    dry_run: bool,
) -> Result:
    """Update one project, unless it has uncommitted changes."""
    before = git_state(project)
    result = Result(project, before.branch)
    if before.changed and not dirty:
        result.status = Status.SKIPPED
        result.notes.append(f"{before.changed} uncommitted files, --dirty includes it")
        return result
    if not dry_run:
        print(f"\n==> {project.name} ({before.branch})", flush=True)  # noqa: T201
    result.status, result.notes = run_steps(project, steps, env, dry_run=dry_run)
    if not dry_run and (after := git_state(project).changed):
        result.notes.append(f"{after} uncommitted files")
    return result


def print_summary(results: Sequence[Result]) -> None:
    """Print one aligned line per project."""
    if not results:
        return
    name_width = max(len(r.project.name) for r in results)
    branch_width = max(len(r.branch) for r in results)
    status_width = max(len(r.status) for r in results)
    print("\nSummary:")  # noqa: T201
    for r in results:
        line = (
            f"  {r.status:<{status_width}}  {r.project.name:<{name_width}}"
            f"  {r.branch:<{branch_width}}  {'; '.join(r.notes)}"
        )
        print(line.rstrip())  # noqa: T201


def select(projects: Sequence[Path], names: Sequence[str], root: Path) -> list[Path]:
    """Keep the named projects, or all of them when none are named."""
    if not names:
        return list(projects)
    wanted = {Path(name).name for name in names}
    if unknown := wanted - {p.name for p in projects}:
        sys.exit(f"not devenv projects in {root}: {', '.join(sorted(unknown))}")
    return [p for p in projects if p.name in wanted]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run make update-devenv in every devenv project beside devenv."
    )
    parser.add_argument(
        "projects", nargs="*", help="update only these projects (default: all)"
    )
    parser.add_argument(
        "-u", "--update", action="store_true", help="then run make update"
    )
    parser.add_argument("-f", "--fix", action="store_true", help="then run make fix")
    parser.add_argument(
        "-d",
        "--dirty",
        action="store_true",
        help="also update projects with uncommitted changes",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="list the projects, run nothing"
    )
    parser.add_argument(
        "--no-update-deps",
        action="store_true",
        help="pass --no-update-deps to update-devenv",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Update every selected project and return the exit status."""
    args = _parse_args(argv)
    devenv_src = get_devenv_src()
    root = code_root(devenv_src)
    projects = select(find_projects(root), args.projects, root)
    steps = [
        ["update-devenv"]
        + (["UPDATE_DEVENV_FLAGS=--no-update-deps"] if args.no_update_deps else []),
        *([["update"]] if args.update else []),
        *([["fix"]] if args.fix else []),
    ]
    env = child_env(devenv_src)
    print(f"devenv: {devenv_src}\n{len(projects)} projects in {root}")  # noqa: T201

    # Appended one by one, so an interrupt still summarizes the projects done.
    results: list[Result] = []
    status = 0
    try:
        for project in projects:
            results.append(  # noqa: PERF401
                update(project, steps, env, dirty=args.dirty, dry_run=args.dry_run)
            )
    except KeyboardInterrupt:
        status = _INTERRUPTED
    print_summary(results)
    if status:
        print(f"Interrupted; {len(projects) - len(results)} projects not run")  # noqa: T201
    elif any(r.status is Status.FAILED for r in results):
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
