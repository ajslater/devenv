"""
The pyproject template's codespell skips.

codespell fnmatches each skip pattern against every dir it walks ("." and
"./pkg"), every dir and file name, and every file path ("./pkg/mod.py"). It
skips hidden files and dirs itself, except the "." it walks from.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import tomlkit

if TYPE_CHECKING:
    from collections.abc import Iterable

codespell_lib = pytest.importorskip("codespell_lib")

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
_SCANNED = ("mod.py", "pkg/mod.py", "pkg/sub/mod.py", "distro/mod.py")
_SKIPPED = (
    ".git/config",
    ".gitignore",
    ".venv/lib/mod.py",
    "pkg/.cache/mod.py",
    "__pycache__/mod.txt",
    "bun.lock",
    "dist/mod.txt",
    "doc.pdf",
    "htmlcov/index.html",
    "logo.svg",
    "mod.py~",
    "node_modules/pkg/index.js",
    "package.json",
    "pkg/node_modules/pkg/index.js",
    "test-results/results.xml",
    "typings/mod.pyi",
    "uv.lock",
)


def _write_misspelled(root: Path, paths: Iterable[str]) -> None:
    for path in paths:
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("Teh\n")  # codespell:ignore teh


def test_codespell_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`codespell .` checks the project's files and skips the rest."""
    codespell = tomlkit.parse(_TEMPLATE.read_text())["tool"]["codespell"]
    (tmp_path / "pyproject.toml").write_text(
        tomlkit.dumps({"tool": {"codespell": codespell}})
    )
    _write_misspelled(tmp_path, (*_SCANNED, *_SKIPPED))
    monkeypatch.chdir(tmp_path)

    codespell_lib.main(".")

    reported = {line.split(":")[0] for line in capsys.readouterr().out.splitlines()}
    assert reported == {f"./{path}" for path in _SCANNED}
