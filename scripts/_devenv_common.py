"""Shared utilities for devenv scripts."""  # noqa: INP001

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

ALL_FEATURES = (
    "ci",
    "common",
    "docker",
    "docs",
    "django",
    "frontend",
    "gha_std",
    "node",
    "node_root",
    "python",
)


def get_devenv_src() -> Path:
    """Get the devenv source directory."""
    if src := os.environ.get("DEVENV_SRC"):
        return Path(src).resolve()
    return Path(__file__).resolve().parent.parent


def get_enabled_features() -> list[str]:
    """Return features whose DEVENV_<FEATURE> env var is set."""
    return [f for f in ALL_FEATURES if os.environ.get(f"DEVENV_{f.upper()}")]


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


def format_makefiles(files: Sequence[Path]) -> None:
    """
    Format Makefiles via mbake's Python API.

    Skips with a warning when mbake isn't importable — this happens during initial
    project setup, before the lint dependency group has been synced.
    """
    if not files:
        return
    try:
        from mbake import Config, MakefileFormatter
    except ImportError:
        print("Warning: mbake not installed; skipping Makefile formatting.")  # noqa: T201
        return

    formatter = MakefileFormatter(Config.load_or_default())
    all_errors: list[str] = []
    for path in files:
        _changed, errors, _warnings = formatter.format_file(path)
        all_errors.extend(f"{path}: {e}" for e in errors)
    if all_errors:
        raise RuntimeError("mbake formatting failed:\n" + "\n".join(all_errors))
