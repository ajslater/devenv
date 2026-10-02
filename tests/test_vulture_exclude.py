"""
The pyproject template's vulture excludes.

vulture resolves every module it finds and fnmatches the absolute path against
each exclude pattern, so a pattern must match the whole absolute path of a file
to exclude it, and must not match the dirs above the project root.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import pytest
import tomlkit

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
# vulture matches the resolved path, so every file is under the checkout's path,
# which may itself be under a hidden dir, as a Claude Code worktree is.
_CHECKOUTS = ("/home/dev/project", "/home/dev/.claude/worktrees/x", "/srv/website")


def _excluded(checkout: str, path: str) -> bool:
    """Match path against the template's excludes as Vulture.scavenge() does."""
    patterns = tomlkit.parse(_TEMPLATE.read_text())["tool"]["vulture"]["exclude"]
    patterns = [p if any(c in p for c in "*?[") else f"*{p}*" for p in patterns]
    return any(fnmatch(f"{checkout}/{path}", pattern) for pattern in patterns)


@pytest.mark.parametrize("checkout", _CHECKOUTS)
@pytest.mark.parametrize(
    "path",
    [
        # katex ships a .py file and arrives through @eslint/markdown.
        "node_modules/katex/src/fonts/generate_fonts.py",
        "web/node_modules/pkg/setup.py",
        ".venv/lib/python3.14/site-packages/pkg/mod.py",
        "dist/pkg/mod.py",
        "frontend/pkg/mod.py",
        "site/pkg/mod.py",
        "test-results/pkg/mod.py",
        "typings/pkg/mod.py",
    ],
)
def test_vulture_excludes(checkout: str, path: str) -> None:
    """Files under dependency, virtualenv, build and cache dirs are not scanned."""
    assert _excluded(checkout, path)


@pytest.mark.parametrize("checkout", _CHECKOUTS)
@pytest.mark.parametrize(
    "path",
    [
        "pkg/mod.py",
        "tests/test_mod.py",
        "pkg/node_modules_shim.py",
        "pkg/composite.py",
        "pkg/redist/mod.py",
    ],
)
def test_vulture_scans(checkout: str, path: str) -> None:
    """The project's own modules are scanned."""
    assert not _excluded(checkout, path)
