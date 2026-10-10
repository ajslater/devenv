"""
Retiring config that devenv used to ship.

A child repo sheds these on its next update-devenv:

- update_devenv deletes the files listed in remove_files.txt.
- merge_dotfiles drops the lines in remove_dotfile_lines.txt from every merged
  dotfile.
- merge_toml --remove-values drops the values in
  merge/python/pyproject-template.remove.toml from pyproject.toml's arrays and
  comma-delimited strings, dropping any it empties, and drops each key that
  holds a scalar it lists.
- merge_package_json --remove-values drops the values in
  merge/node_root/package.remove.json from package.json's arrays and the
  commands it lists from package.json's scripts.
- merge_package_json --remove drops the packages in remove_node_packages.txt
  from every dependency section of package.json.
"""

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
import update_devenv
from _devenv_common import read_lines

from scripts import merge_package_json, merge_toml

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT_REMOVE = _ROOT / "merge" / "python" / "pyproject-template.remove.toml"
_PYPROJECT_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
_PACKAGE_REMOVE = _ROOT / "merge" / "node_root" / "package.remove.json"
_PACKAGE_TEMPLATE = _ROOT / "merge" / "node_root" / "package.json"
_PACKAGE_INIT_TEMPLATE = _ROOT / "init" / "node_root" / "package.json"
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
        if template.is_file() and merge_dotfiles._is_dotfile(template.name):  # noqa: SLF001
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


def test_remove_values_keeps_whether_an_array_ends_in_a_comma() -> None:
    """Dropping an array's last item keeps whether the array ends in a comma."""
    doc = tomlkit.parse("""\
[tool.a]
bare = [
  "a",
  "b",
  "c"
]
comma = [
  "a",
  "b",
  "c",
]
""")
    retired = tomlkit.parse('[tool.a]\nbare = ["c"]\ncomma = ["c"]\n')

    merge_toml.remove_values(doc, retired)

    assert (
        tomlkit.dumps(doc)
        == """\
[tool.a]
bare = [
  "a",
  "b"
]
comma = [
  "a",
  "b",
]
"""
    )


def test_remove_values_drops_items_from_comma_delimited_strings() -> None:
    """A retired item leaves a comma-delimited string; the rest keep their order."""
    doc = tomlkit.parse('[tool.codespell]\nskip = "z,.*,a,.*/*"\nother = "z,.*"\n')
    retired = tomlkit.parse('[tool.codespell]\nskip = [".*", ".*/*"]\n')

    merge_toml.remove_values(doc, retired)

    assert doc["tool"]["codespell"]["skip"] == "z,a"
    assert doc["tool"]["codespell"]["other"] == "z,.*"


def test_remove_values_drops_keys_holding_a_retired_scalar() -> None:
    """A retired scalar drops its key, and the table it empties, only on a match."""
    doc = tomlkit.parse("[tool.a]\nflag = true\n\n[tool.b]\nflag = false\n")
    retired = tomlkit.parse("[tool.a]\nflag = true\n\n[tool.b]\nflag = true\n")

    merge_toml.remove_values(doc, retired)

    assert "a" not in doc["tool"]
    assert doc["tool"]["b"]["flag"] is False


def test_merge_toml_cli_retires_codespell_hidden_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project sheds the codespell globs that skipped its whole tree."""
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[tool.codespell]\ncheck-hidden = true\nskip = "*~,.*,.*/*,comics,uv.lock"\n'
    )
    argv = ["merge_toml.py", str(_PYPROJECT_TEMPLATE), str(project)]
    argv += ["-o", str(project), "--remove-values", str(_PYPROJECT_REMOVE)]
    monkeypatch.setattr(sys, "argv", argv)

    merge_toml.main()

    codespell = tomlkit.parse(project.read_text())["tool"]["codespell"]
    assert "check-hidden" not in codespell
    skip = codespell["skip"].split(",")
    assert not {".*", ".*/*"} & set(skip)
    assert "comics" in skip


def test_merge_toml_cli_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--remove-values applies pyproject-template.remove.toml after the merge."""
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


def test_remove_values_prunes_emptied_keys() -> None:
    """
    An array or string emptied by retirement goes; one with a survivor stays.

    Only keys on a retired path are pruned, so an intentionally empty array
    elsewhere is untouched.
    """
    doc = tomlkit.parse("""\
[tool.a]
gone = ["x"]
gone_csv = "x,y"
kept = ["x", "y"]
empty = []
""")
    retired = tomlkit.parse("""\
[tool.a]
gone = ["x"]
gone_csv = ["x", "y"]
kept = ["x"]
""")

    merge_toml.remove_values(doc, retired)

    assert tomlkit.dumps(doc) == '[tool.a]\nkept = ["y"]\nempty = []\n'


def test_complexipy_exclude_is_retired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Every value the template shipped in complexipy's exclude matched nothing.

    update-devenv drops them, and the key with them unless the project added
    its own value.
    """
    shipped = tomlkit.parse(_PYPROJECT_REMOVE.read_text())["tool"]["complexipy"]
    project = tmp_path / "pyproject.toml"
    for own, expected in (([], None), (["migrations/**"], ["migrations/**"])):
        exclude = [*shipped["exclude"], *own]
        table = {"failed": True, "paths": ["pkg", "tests"], "exclude": exclude}
        project.write_text(tomlkit.dumps({"tool": {"complexipy": table}}))
        argv = ["merge_toml.py", str(_PYPROJECT_TEMPLATE), str(project)]
        argv += ["-o", str(project), "--remove-values", str(_PYPROJECT_REMOVE)]
        monkeypatch.setattr(sys, "argv", argv)

        merge_toml.main()

        merged = tomlkit.parse(project.read_text())["tool"]["complexipy"]
        assert merged.get("exclude") == expected
        assert merged["paths"] == ["pkg", "tests"]


def test_template_ships_no_retired_value() -> None:
    """The template must not reintroduce what pyproject-template.remove.toml retires."""
    retired = tomlkit.parse(_PYPROJECT_REMOVE.read_text())
    template = tomlkit.parse(_PYPROJECT_TEMPLATE.read_text())
    before = tomlkit.dumps(template)

    merge_toml.remove_values(template, retired)

    assert tomlkit.dumps(template) == before


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------


def _removed_node_packages() -> list[str]:
    return read_lines(_ROOT / "remove_node_packages.txt")


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
    assert _SH_PLUGIN in _removed_node_packages()


def test_package_remove_values_retires_script_step() -> None:
    """A retired command leaves its script's && chain; the other steps stay."""
    data = {"scripts": {"lint": "a && b && c", "fix": "a && c"}}
    retired = {"scripts": {"lint": ["b"], "missing": ["b"]}}

    merge_package_json.remove_values(data, retired)

    assert data == {"scripts": {"lint": "a && c", "fix": "a && c"}}


def test_package_remove_values_prunes_emptied_containers() -> None:
    """
    A config key emptied by retirement goes; one with a survivor stays.

    Only keys on a retired path are pruned, so an intentionally empty array
    elsewhere is untouched.
    """
    retired = {"remarkConfig": {"plugins": ["gfm", "preset-prettier"]}}
    emptied = {
        "remarkConfig": {"plugins": ["gfm", "preset-prettier"]},
        "files": [],
    }
    survivor = {"remarkConfig": {"plugins": ["gfm"], "settings": {"bullet": "-"}}}

    merge_package_json.remove_values(emptied, retired)
    merge_package_json.remove_values(survivor, retired)

    assert emptied == {"files": []}
    assert survivor == {"remarkConfig": {"settings": {"bullet": "-"}}}


def test_package_remove_retires_remark() -> None:
    """@eslint/markdown replaced remark; retire its config, script and packages."""
    retired = json.loads(_PACKAGE_REMOVE.read_text())
    assert set(retired["remarkConfig"]["plugins"]) == {
        "gfm",
        "lint",
        "preset-lint-consistent",
        "preset-lint-markdown-style-guide",
        "preset-lint-recommended",
        "preset-prettier",
    }
    assert retired["scripts"]["lint"] == ["bin/remark-for-claude.sh"]
    removed_packages = set(_removed_node_packages())
    assert {
        "eslint-plugin-mdx",
        "remark-cli",
        "remark-gfm",
        "remark-preset-lint-consistent",
        "remark-preset-lint-markdown-style-guide",
        "remark-preset-lint-recommended",
        "remark-preset-prettier",
    } <= removed_packages


def test_template_ships_no_removed_package() -> None:
    """A template that still listed a retired package would reinstall it."""
    removed_packages = set(_removed_node_packages())
    for template in (_PACKAGE_TEMPLATE, _PACKAGE_INIT_TEMPLATE):
        dev_dependencies = json.loads(template.read_text()).get("devDependencies", {})
        assert not removed_packages & dev_dependencies.keys(), template


def test_merge_package_json_cli_remove_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--remove-values applies package.remove.json after the merge."""
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


def test_merge_package_json_cli_remove_reaches_every_dependency_section(
    tmp_path: Path,
) -> None:
    """
    --remove drops retired packages from sections the template lacks too.

    A section the retirement empties goes; the project's own packages stay.
    """
    project = tmp_path / "package.json"
    project.write_text(
        json.dumps(
            {
                "dependencies": {"remark-cli": "^12.0.0", "left-pad": "^1.3.0"},
                "devDependencies": {"remark-gfm": "^4.0.0", "prettier": "^3.0.0"},
                "optionalDependencies": {"remark-preset-prettier": "^2.0.0"},
                "peerDependencies": {"eslint-plugin-mdx": "^3.0.0", "react": "^18.0.0"},
                "bundledDependencies": ["left-pad", "remark-cli"],
            }
        )
    )
    argv = [str(_PACKAGE_TEMPLATE), str(project), "-o", str(project)]
    argv += ["--remove", str(_ROOT / "remove_node_packages.txt")]

    merge_package_json.main(argv)

    merged = json.loads(project.read_text())
    assert merged["dependencies"] == {"left-pad": "^1.3.0"}
    assert "remark-gfm" not in merged["devDependencies"]
    assert "prettier" in merged["devDependencies"]
    assert "optionalDependencies" not in merged
    assert merged["peerDependencies"] == {"react": "^18.0.0"}
    assert merged["bundledDependencies"] == ["left-pad"]


def test_merge_package_json_cli_retires_a_script_step_the_project_moved(
    tmp_path: Path,
) -> None:
    """A retired step goes wherever the project put it; its own steps stay."""
    project = tmp_path / "package.json"
    lint = "bin/remark-for-claude.sh && tsc --noEmit && eslint_d --cache ."
    project.write_text(json.dumps({"scripts": {"lint": lint}}))
    argv = [str(_PACKAGE_TEMPLATE), str(project), "-o", str(project)]
    argv += ["--remove-values", str(_PACKAGE_REMOVE)]

    merge_package_json.main(argv)

    scripts = json.loads(project.read_text())["scripts"]
    assert scripts["lint"] == "tsc --noEmit && eslint_d --cache . && prettier --check ."


def test_package_template_ships_no_retired_value() -> None:
    """The template must not reintroduce what package.remove.json retires."""
    template = json.loads(_PACKAGE_TEMPLATE.read_text())
    before = json.dumps(template)

    merge_package_json.remove_values(template, json.loads(_PACKAGE_REMOVE.read_text()))

    assert json.dumps(template) == before


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _removed_files() -> set[str]:
    return set(read_lines(_ROOT / "remove_files.txt"))


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


# ---------------------------------------------------------------------------
# Retirement siblings
# ---------------------------------------------------------------------------


def test_every_remove_file_pairs_with_a_template() -> None:
    """A .remove file without its template would never be applied."""
    removes = sorted((_ROOT / "merge").glob("*/*.remove.*"))
    assert removes
    for remove in removes:
        stem, ext = remove.name.split(".remove", 1)
        assert (remove.parent / f"{stem}{ext}").is_file(), remove


def test_update_passes_each_templates_sibling(tmp_path: Path) -> None:
    """update-devenv retires through the sibling of every template it merges."""
    calls: list[list[str]] = []

    def merger(argv: Sequence[str]) -> None:
        calls.append(list(argv))

    merge = update_devenv.ConfigMerge(
        "python", merger, "pyproject-template.toml", "pyproject.toml"
    )

    update_devenv.merge_config(_ROOT, tmp_path, ["python", "django"], merge)

    (argv,) = calls
    assert argv[argv.index("--remove-values") + 1] == str(_PYPROJECT_REMOVE)
