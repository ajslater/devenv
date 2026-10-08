"""Shared utilities for devenv scripts."""  # noqa: INP001

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
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

# The devenv version that last updated a project, written into the project.
STAMP_FILE: Final = ".devenv-version"
_SINCE_RE = re.compile(r"#\s*since\s+v?(?P<version>\d+(?:\.\d+)*)")

type Version = tuple[int, ...]


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


def parse_version(text: str) -> Version:
    """Parse "1.2.3" or "v1.2.3" into a comparable tuple."""
    return tuple(int(part) for part in text.strip().removeprefix("v").split("."))


def devenv_version(devenv_src: Path) -> str | None:
    """Return devenv's own version, from its pyproject.toml."""
    path = devenv_src / "pyproject.toml"
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text()).get("project", {}).get("version")


def read_stamp(project: Path) -> Version | None:
    """Return the devenv version that last updated project, if it says."""
    path = project / STAMP_FILE
    return parse_version(path.read_text()) if path.is_file() else None


def read_lines(path: Path, stamp: Version | None = None) -> list[str]:
    """
    Read a list file: one entry per line; blanks and `#` lines are skipped.

    In a retirement list, a `# since X.Y.Z` line marks the entries below it as
    retired in devenv X.Y.Z; entries above the first marker predate stamping.
    A project stamped with version S already had every entry from S or
    earlier applied, so given a stamp, only newer entries are returned. That
    lets a project keep a file of its own that devenv once shipped and
    retired under the same name.
    """
    if not path.exists():
        return []
    since: Version = ()
    entries: list[str] = []
    for line in path.read_text().splitlines():
        entry = line.strip()
        if match := _SINCE_RE.fullmatch(entry):
            since = parse_version(match["version"])
        elif entry and not entry.startswith("#") and (stamp is None or since > stamp):
            entries.append(entry)
    return entries


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
