"""
Every devenv script declares what it imports (PEP 723).

`uv run scripts/<name>.py` builds each script its own environment from its
inline metadata, so an undeclared import only works while some other
environment happens to provide it.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_METADATA_RE = re.compile(
    r"^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$", re.MULTILINE
)
# Import names whose distribution is named differently.
_DISTRIBUTIONS = {"yaml": "pyyaml", "ruamel": "ruamel.yaml"}
_ENTRY_POINTS = sorted(
    path.name
    for path in _SCRIPTS.glob("*.py")
    if path.read_text().startswith("#!/usr/bin/env python3")
)


def _metadata(path: Path) -> dict:
    match = _METADATA_RE.search(path.read_text())
    assert match, f"{path.name} has no PEP 723 script metadata"
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in match["content"].splitlines(keepends=True)
    )
    return tomllib.loads(content)


def _imported_names(path: Path) -> set[str]:
    """Top-level names of the absolute imports in path."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        match node:
            case ast.Import(names=aliases):
                names.update(alias.name.split(".")[0] for alias in aliases)
            case ast.ImportFrom(module=str(module), level=0):
                names.add(module.split(".")[0])
            case _:
                pass
    return names - set(sys.stdlib_module_names)


def _imports(path: Path, seen: set[Path]) -> set[str]:
    """Third-party names imported by path and the local modules it imports."""
    seen.add(path)
    third_party: set[str] = set()
    for name in _imported_names(path):
        local = _SCRIPTS / f"{name}.py"
        if not local.is_file():
            third_party.add(name)
        elif local not in seen:
            third_party |= _imports(local, seen)
    return third_party


def test_entry_points_found() -> None:
    """Guard the glob: these are the scripts devenv runs with `uv run`."""
    assert {"add_features.py", "copy_files.py", "update_devenv.py"} <= set(
        _ENTRY_POINTS
    )


@pytest.mark.parametrize("name", _ENTRY_POINTS)
def test_imports_are_declared(name: str) -> None:
    """Each third-party import, also via sibling modules, is a dependency."""
    path = _SCRIPTS / name
    declared = {
        Requirement(dep).name.lower() for dep in _metadata(path).get("dependencies", [])
    }
    needed = {_DISTRIBUTIONS.get(n, n) for n in _imports(path, set())}

    assert needed <= declared, f"{name} imports undeclared {needed - declared}"
    assert declared <= needed, f"{name} declares unused {declared - needed}"


@pytest.mark.parametrize("name", _ENTRY_POINTS)
def test_requires_python(name: str) -> None:
    """The mergers use 3.14 syntax, so every entry point says so."""
    assert _metadata(_SCRIPTS / name)["requires-python"] == ">=3.14"
