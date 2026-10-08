"""Shared utilities for devenv scripts."""  # noqa: INP001

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class Feature:
    """A DEVENV_<FEATURE> flag: what it needs, and whether new projects get it."""

    requires: tuple[str, ...] = ()
    default: bool = False


# The one list of features, in the order a project Makefile includes them.
# The order is load-bearing: OVERRIDE_* is read when python.mk is parsed, and
# `::` recipes run in include order, so django's collectstatic precedes the
# python build.
FEATURES: Final = MappingProxyType(
    {
        "django": Feature(requires=("frontend", "python")),
        "frontend": Feature(),
        "python": Feature(default=True),
        "ci": Feature(requires=("python",)),
        "gha_std": Feature(requires=("ci",)),
        "docker": Feature(),
        "docs": Feature(requires=("python",)),
        "node": Feature(default=True),
        "node_root": Feature(default=True),
        "common": Feature(requires=("python", "node_root"), default=True),
    }
)
DEFAULT_FEATURES: Final = tuple(name for name, f in FEATURES.items() if f.default)


def get_devenv_src() -> Path:
    """Get the devenv source directory."""
    if src := os.environ.get("DEVENV_SRC"):
        return Path(src).resolve()
    return Path(__file__).resolve().parent.parent


def get_enabled_features() -> list[str]:
    """Return features whose DEVENV_<FEATURE> env var is set."""
    return [f for f in FEATURES if os.environ.get(f"DEVENV_{f.upper()}")]


def unmet_requirements(features: Collection[str]) -> list[str]:
    """Return one message per unknown feature or missing required feature."""
    problems = [f"unknown feature '{f}'" for f in features if f not in FEATURES]
    problems += [
        f"feature '{f}' requires '{req}'"
        for f in features
        if f in FEATURES
        for req in FEATURES[f].requires
        if req not in features
    ]
    return problems


def exit_on_unmet_requirements(features: Collection[str]) -> None:
    """Exit with a one-line message per problem if a feature is missing."""
    if problems := unmet_requirements(features):
        sys.exit("\n".join(f"devenv: {problem}" for problem in problems))


def read_lines(path: Path) -> list[str]:
    """Read a list file: one entry per line; blanks and `#` lines are skipped."""
    if not path.exists():
        return []
    return [
        entry
        for line in path.read_text().splitlines()
        if (entry := line.strip()) and not entry.startswith("#")
    ]


def missing_tools(tools: Iterable[str]) -> list[str]:
    """Return the tools that are not on PATH."""
    return [tool for tool in tools if not shutil.which(tool)]


def iter_feature_dirs(
    base: Path, features: list[str] | None = None
) -> Iterator[tuple[str, Path]]:
    """Yield (feature_name, feature_dir) for each enabled feature with a dir under base."""
    if features is None:
        features = get_enabled_features()
    for feature in features:
        feature_dir = base / feature
        if feature_dir.is_dir():
            yield feature, feature_dir


def report_counts(label: str, **counts: int) -> None:
    """Print a summary like 'Copied files: 3 copied 2 skipped'."""
    if not any(counts.values()):
        return
    parts = [f"{label}:"]
    for name, count in counts.items():
        if count:
            parts.append(f" {count} {name}")
    print("".join(parts))  # noqa: T201


def git_status(files: Sequence[Path | str]) -> None:
    """Show git status for the given files."""
    if files:
        subprocess.run(  # noqa: S603
            ["git", "status", "--short", *[str(f) for f in files]],  # noqa: S607
            check=False,
        )


def run(cmd: list[str | Path], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a command with check=True."""
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)  # noqa: S603
