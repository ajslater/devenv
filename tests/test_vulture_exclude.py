"""
The pyproject template's vulture excludes.

vulture resolves every module it finds and fnmatches the absolute path against
each exclude pattern, so a pattern must match the whole absolute path of a file
to exclude it.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import pytest
import tomlkit

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
# vulture matches the resolved path, so every file is under the checkout's path.
_REPO = "/home/dev/project"


def _excluded(path: str) -> bool:
    """Match path against the template's excludes as Vulture.scavenge() does."""
    patterns = tomlkit.parse(_TEMPLATE.read_text())["tool"]["vulture"]["exclude"]
    patterns = [p if any(c in p for c in "*?[") else f"*{p}*" for p in patterns]
    return any(fnmatch(f"{_REPO}/{path}", pattern) for pattern in patterns)


@pytest.mark.parametrize(
    "path",
    [
        # katex ships a .py file and arrives through @eslint/markdown.
        "node_modules/katex/src/fonts/generate_fonts.py",
        "web/node_modules/pkg/setup.py",
        ".venv/lib/python3.14/site-packages/pkg/mod.py",
        "pkg/__pycache__/mod.py",
    ],
)
def test_vulture_excludes(path: str) -> None:
    """Files under dependency, hidden and cache dirs are not scanned."""
    assert _excluded(path)


@pytest.mark.parametrize(
    "path", ["pkg/mod.py", "tests/test_mod.py", "pkg/node_modules_shim.py"]
)
def test_vulture_scans(path: str) -> None:
    """The project's own modules are scanned."""
    assert not _excluded(path)
