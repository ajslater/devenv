"""
Retiring config that devenv used to ship.

A child repo sheds these on its next update-devenv:

- update_devenv deletes the files listed in remove_files.txt.
- merge_dotfiles drops the lines in remove_dotfile_lines.txt from every merged
  dotfile.
- merge_toml --remove-values drops the values in
  merge/python/pyproject-remove.toml from pyproject.toml's arrays.
- merge_package_json --remove-values drops the values in
  merge/node_root/package-remove.json from package.json's arrays.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit

from scripts import merge_package_json, merge_toml

if TYPE_CHECKING:
    import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT_REMOVE = _ROOT / "merge" / "python" / "pyproject-remove.toml"
_PYPROJECT_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
_PACKAGE_REMOVE = _ROOT / "merge" / "node_root" / "package-remove.json"
_PACKAGE_TEMPLATE = _ROOT / "merge" / "node_root" / "package.json"
_SH_PLUGIN = "prettier-plugin-sh"
_SH_OVERRIDE = {"files": ["**/*Dockerfile"], "options": {"parser": "sh"}}
_XSD_OVERRIDE = {"files": ["**/*.xsd"], "options": {"printWidth": 120}}
# merge_dotfiles imports its sibling _devenv_common as a top-level module.
sys.path.insert(0, str(_ROOT / "scripts"))
merge_dotfiles = importlib.import_module("merge_dotfiles")

_PYPROJECT = """\
[tool.uv.build-backend]
source-include = [
  ".circlci/**",
  "NEWS.md",
  "bin/**",
]
other = [".circlci/**"]
"""


# ---------------------------------------------------------------------------
# Dotfiles
# ---------------------------------------------------------------------------


def test_retired_dotfile_lines_are_dropped(tmp_path: Path) -> None:
    """A retired line leaves the project's file; its own lines stay."""
    templates = tmp_path / "merge"
    (templates / "common").mkdir(parents=True)
    (templates / "common" / ".prettierignore").write_text("node_modules\n")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".prettierignore").write_text(".circleci\nmine\n")

    merge_dotfiles.merge_dotfiles(
        templates, project, ["common"], frozenset({".circleci"})
    )

    assert (project / ".prettierignore").read_text() == "mine\nnode_modules\n"


def test_devenv_retires_circleci() -> None:
    """remove_dotfile_lines.txt retires the CircleCI directory."""
    assert ".circleci" in merge_dotfiles.read_retired_lines(_ROOT)


def test_no_template_ships_a_retired_line() -> None:
    """A template that still shipped a retired line would fight the retirement."""
    retired = merge_dotfiles.read_retired_lines(_ROOT)
    for template in sorted((_ROOT / "merge").glob("*/.*")):
        if template.is_file() and not template.name.endswith("~"):
            shipped = set(template.read_text().splitlines())
            assert not shipped & retired, template


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------


def test_remove_values_drops_only_listed_values() -> None:
    """Only the listed value at the listed key path goes; formatting stays."""
    doc = tomlkit.parse(_PYPROJECT)
    retired = tomlkit.parse("""\
[tool.uv.build-backend]
source-include = [".circlci/**"]

[tool.missing]
key = ["x"]
""")

    merge_toml.remove_values(doc, retired)

    backend = doc["tool"]["uv"]["build-backend"]
    assert backend["source-include"] == ["NEWS.md", "bin/**"]
    assert backend["other"] == [".circlci/**"]
    assert '\n  "NEWS.md",\n  "bin/**",\n' in tomlkit.dumps(doc)


def test_merge_toml_cli_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--remove-values applies pyproject-remove.toml after the merge."""
    template = tmp_path / "template.toml"
    template.write_text('[tool.uv.build-backend]\nsource-include = ["NEWS.md"]\n')
    project = tmp_path / "pyproject.toml"
    project.write_text(_PYPROJECT)
    argv = ["merge_toml.py", str(template), str(project), "-o", str(project)]
    argv += ["--remove-values", str(_PYPROJECT_REMOVE)]
    monkeypatch.setattr(sys, "argv", argv)

    merge_toml.main()

    merged = tomlkit.parse(project.read_text())
    source_include = merged["tool"]["uv"]["build-backend"]["source-include"]
    assert ".circlci/**" not in source_include
    assert "NEWS.md" in source_include


def test_template_ships_no_retired_value() -> None:
    """The template must not reintroduce what pyproject-remove.toml retires."""
    retired = tomlkit.parse(_PYPROJECT_REMOVE.read_text())
    template = tomlkit.parse(_PYPROJECT_TEMPLATE.read_text())
    before = tomlkit.dumps(template)

    merge_toml.remove_values(template, retired)

    assert tomlkit.dumps(template) == before


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------


def _package(*, plugins: list[str], overrides: list[dict]) -> dict:
    return {
        "name": "demo",
        "devDependencies": {"prettier": "^3.0.0"},
        "prettier": {"plugins": plugins, "overrides": overrides},
    }


def test_package_remove_values_drops_only_whole_matches() -> None:
    """A retired object goes only when every field matches."""
    near_miss = {"files": ["**/*Dockerfile"], "options": {"parser": "babel"}}
    data = _package(
        plugins=["prettier-plugin-toml", _SH_PLUGIN],
        overrides=[_XSD_OVERRIDE, _SH_OVERRIDE, near_miss],
    )
    retired = {
        "prettier": {"plugins": [_SH_PLUGIN], "overrides": [_SH_OVERRIDE]},
        "missing": {"key": ["x"]},
    }

    merge_package_json.remove_values(data, retired)

    assert data["prettier"] == {
        "plugins": ["prettier-plugin-toml"],
        "overrides": [_XSD_OVERRIDE, near_miss],
    }


def test_package_remove_retires_prettier_plugin_sh() -> None:
    """
    prettier-plugin-sh is no longer installed and fights shfmt.

    Retire its plugin entry and the Dockerfile override that needs its parser.
    """
    retired = json.loads(_PACKAGE_REMOVE.read_text())
    assert retired["prettier"]["plugins"] == [_SH_PLUGIN]
    assert retired["prettier"]["overrides"] == [_SH_OVERRIDE]
    removed_packages = (_ROOT / "remove_node_packages.txt").read_text().splitlines()
    assert _SH_PLUGIN in removed_packages


def test_merge_package_json_cli_remove_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--remove-values applies package-remove.json after the merge."""
    project = tmp_path / "package.json"
    project.write_text(
        json.dumps(
            _package(
                plugins=[_SH_PLUGIN, "prettier-plugin-toml"],
                overrides=[_SH_OVERRIDE, _XSD_OVERRIDE],
            )
        )
    )
    argv = ["merge_package_json.py", str(_PACKAGE_TEMPLATE), str(project)]
    argv += ["-o", str(project)]
    argv += ["--remove", str(_ROOT / "remove_node_packages.txt")]
    argv += ["--remove-values", str(_PACKAGE_REMOVE)]
    monkeypatch.setattr(sys, "argv", argv)

    merge_package_json.main()

    prettier = json.loads(project.read_text())["prettier"]
    assert _SH_PLUGIN not in prettier["plugins"]
    assert "prettier-plugin-toml" in prettier["plugins"]
    assert _SH_OVERRIDE not in prettier["overrides"]
    assert _XSD_OVERRIDE in prettier["overrides"]


def test_package_template_ships_no_retired_value() -> None:
    """The template must not reintroduce what package-remove.json retires."""
    template = json.loads(_PACKAGE_TEMPLATE.read_text())
    before = json.dumps(template)

    merge_package_json.remove_values(template, json.loads(_PACKAGE_REMOVE.read_text()))

    assert json.dumps(template) == before


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _removed_files() -> set[str]:
    lines = (_ROOT / "remove_files.txt").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_old_gate_script_is_retired() -> None:
    """bin/ci-reuse-dist.sh replaced it; child repos delete their copy."""
    assert "bin/ci-download-dist-if-identical.sh" in _removed_files()
    assert (_ROOT / "copy" / "ci" / "bin" / "ci-reuse-dist.sh").is_file()


def test_no_copied_file_is_also_removed() -> None:
    """update_devenv deletes before it copies, so a file in both never goes."""
    shipped = {
        str(path.relative_to(feature))
        for feature in (_ROOT / "copy").iterdir()
        if feature.is_dir()
        for path in feature.rglob("*")
        if path.is_file()
    }
    assert not shipped & _removed_files()
