"""
merge_toml's merge.

The project's own pyproject.toml is the base: its values, order, comments and
layout stay, and each template only fills in what the project lacks.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import tomlkit
from tomlkit.items import AoT

from scripts import merge_toml

if TYPE_CHECKING:
    from collections.abc import Iterator

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT_TEMPLATE = _ROOT / "merge" / "python" / "pyproject-template.toml"
_DJANGO_TEMPLATE = _ROOT / "merge" / "django" / "pyproject-template.toml"
_PYPROJECT_REMOVE = _ROOT / "merge" / "python" / "pyproject-template.remove.toml"
_PYPROJECT_INIT = _ROOT / "init" / "python" / "pyproject.toml"
# A child's own pyproject.toml, with the comments, layout and values a merge
# used to mangle.
_EXISTING = """\
# The demo project.
[project]
name = "demo"  # its import name
description = "A demo, with commas, in prose"
version = "1.0.0"

[[project.authors]]
name = "Someone Else"
email = "someone@example.com"

[tool.pytest]
addopts = [
  "-ra",
  # Coverage last.
  "--strict-markers",
  "--cov",
]

[tool.codespell]
skip = "mine,uv.lock"
"""


def _merge(tmp_path: Path, *texts: str) -> str:
    """Merge texts in order, the last as the project, and return the result."""
    paths = []
    for index, text in enumerate(texts):
        path = tmp_path / f"{index}.toml"
        path.write_text(text)
        paths.append(path)
    return tomlkit.dumps(merge_toml.merge_toml_files(paths))


def _update(project: Path) -> str:
    """Merge the templates into project as update_devenv does; return it."""
    argv = [str(_PYPROJECT_TEMPLATE), str(_DJANGO_TEMPLATE), str(project)]
    argv += ["-o", str(project), "--remove-values", str(_PYPROJECT_REMOVE)]
    merge_toml.main(argv)
    return project.read_text()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_template_arrays_merge_without_a_trailing_comma(tmp_path: Path) -> None:
    """
    A project that lacks a table gets the template's arrays as written.

    prettier-plugin-toml keeps a trailing comma as a request to keep the array
    expanded, so one shipped in the template would stick in every such project.
    """
    project = tmp_path / "pyproject.toml"
    project.touch()

    merged = tomlkit.dumps(merge_toml.merge_toml_files([_PYPROJECT_TEMPLATE, project]))

    assert not re.search(r",[ \t]*(#[^\n]*)?\n[ \t]*\]", merged)


def test_project_comments_and_layout_stay(tmp_path: Path) -> None:
    """The project's comments, blank lines, order and formatting all survive."""
    template = """\
[project]
name = ""
readme = "README.md"

[tool.pytest]
addopts = ["--cov", "--strict-config", "-ra"]
"""

    merged = _merge(tmp_path, template, _EXISTING)

    assert merged == _EXISTING.replace(
        'name = "demo"  # its import name\n',
        'name = "demo"  # its import name\nreadme = "README.md"\n',
    ).replace('  "--cov",\n', '  "--cov",\n  "--strict-config",\n')


def test_missing_keys_take_their_template_places(tmp_path: Path) -> None:
    """Each key the project lacks goes beside its neighbours in the template."""
    project = """\
[project]
name = "demo"
description = "Demo"
version = "1.0.0"

[tool.pytest]
addopts = ["-ra"]
"""
    template = tomlkit.parse(_PYPROJECT_TEMPLATE.read_text())

    merged = tomlkit.parse(_merge(tmp_path, _PYPROJECT_TEMPLATE.read_text(), project))

    assert list(merged) == list(template)
    assert list(merged["tool"]) == list(template["tool"])
    assert list(merged["project"]) == [
        "name",
        "classifiers",
        "dependencies",
        "description",
        "keywords",
        "readme",
        "requires-python",
        "version",
    ]


def test_template_keys_keep_their_comments(tmp_path: Path) -> None:
    """A table the project lacks arrives with the template's comments."""
    merged = _merge(tmp_path, _PYPROJECT_TEMPLATE.read_text(), "")

    assert "# basedpyright also excludes" in merged
    assert "reportPrivateUsage = false  # ruff does this" in merged


# ---------------------------------------------------------------------------
# Scalars and comma lists
# ---------------------------------------------------------------------------


def test_project_scalars_win(tmp_path: Path) -> None:
    """A project's own value beats the template's, commas or not."""
    template = (
        '[project]\ndescription = "Template, with commas"\nreadme = "README.md"\n'
    )
    project = '[project]\ndescription = "A demo, with commas, in prose"\n'

    merged = tomlkit.parse(_merge(tmp_path, template, project))

    assert merged["project"]["description"] == "A demo, with commas, in prose"
    assert merged["project"]["readme"] == "README.md"


def test_comma_lists_keep_the_project_items_first(tmp_path: Path) -> None:
    """An allowlisted comma list keeps its items and appends the template's."""
    template = '[tool.codespell]\nskip = "dist,*.pdf,uv.lock"\nbuiltin = "rare"\n'
    project = '[tool.codespell]\nskip = "uv.lock,mine"\nbuiltin = "clear"\n'

    merged = tomlkit.parse(_merge(tmp_path, template, project))["tool"]["codespell"]

    assert merged["skip"] == "uv.lock,mine,dist,*.pdf"
    assert merged["builtin"] == "clear,rare"


def test_full_comma_list_is_left_as_written(tmp_path: Path) -> None:
    """A comma list that holds every template item keeps its own layout."""
    project = '[tool.radon]\nexclude = """\n  mine/*,\n  dist/*\n  """\n'

    merged = _merge(tmp_path, '[tool.radon]\nexclude = "dist/*"\n', project)

    assert merged == project


def _strings(
    table: object, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Yield the key path and value of each string in table, recursively."""
    if isinstance(table, dict):
        for key, value in table.items():
            yield from _strings(value, (*path, key))
    elif isinstance(table, str):
        yield path, table


def test_template_comma_lists_are_allowlisted() -> None:
    """Every comma list the template ships merges as a list, not as prose."""
    template = tomlkit.parse(_PYPROJECT_TEMPLATE.read_text())

    shipped = {path for path, value in _strings(template) if "," in value}

    assert shipped == merge_toml.COMMA_LIST_KEY_PATHS


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------


def test_arrays_keep_the_project_order(tmp_path: Path) -> None:
    """The project's items keep their order; the template's missing ones follow."""
    template = '[tool.pytest]\naddopts = ["--cov", "--strict-config", "-ra"]\n'
    project = '[tool.pytest]\naddopts = ["-ra", "--strict-markers", "--cov"]\n'

    merged = tomlkit.parse(_merge(tmp_path, template, project))

    assert merged["tool"]["pytest"]["addopts"] == [
        "-ra",
        "--strict-markers",
        "--cov",
        "--strict-config",
    ]


def test_merged_arrays_add_each_template_value_once() -> None:
    """
    A template value the project lacks is added once.

    The project's own repeats stay: pytest's ["-p", "a", "-p", "b"] needs them.
    """
    base = tomlkit.parse('[tool.x]\nexclude = ["b", "a", "b"]\n')
    update = tomlkit.parse('[tool.x]\nexclude = ["c", "a", "c"]\n')

    merged = merge_toml.deep_merge_tomlkit(base, update, "merge")

    assert merged["tool"]["x"]["exclude"] == ["c", "a", "c", "b"]


def test_replace_strategy_keeps_the_project_lists(tmp_path: Path) -> None:
    """--list-strategy replace keeps the project's lists; dependencies merge."""
    template = tmp_path / "template.toml"
    template.write_text("""\
[dependency-groups]
lint = ["ruff~=0.16"]

[tool.codespell]
skip = "dist"

[tool.x]
items = ["a"]
""")
    project = tmp_path / "pyproject.toml"
    project.write_text("""\
[dependency-groups]
lint = ["ty~=0.1"]

[tool.codespell]
skip = "mine"

[tool.x]
items = ["b"]
""")

    merge_toml.main(
        [str(template), str(project), "-o", str(project), "--list-strategy", "replace"]
    )

    merged = tomlkit.parse(project.read_text())
    assert merged["tool"]["x"]["items"] == ["b"]
    assert merged["tool"]["codespell"]["skip"] == "mine"
    assert merged["dependency-groups"]["lint"] == ["ty~=0.1", "ruff~=0.16"]


def test_arrays_of_tables_keep_the_project_tables(tmp_path: Path) -> None:
    """An array of tables is the project's own; the template's never joins it."""
    template = """\
[[project.authors]]
name = "Template"

[tool.x]
items = [{ name = "template" }]
"""
    project = """\
[project]
name = "demo"

[[project.authors]]
name = "Mine"
email = "me@example.com"

[tool.x]
items = [{ name = "mine" }]
"""

    assert _merge(tmp_path, template, project) == project


def test_authors_are_a_starter_value() -> None:
    """The template ships no authors to merge; init's starter file has them."""
    template = tomlkit.parse(_PYPROJECT_TEMPLATE.read_text())
    starter = tomlkit.parse(_PYPROJECT_INIT.read_text())

    assert "authors" not in template["project"]
    assert isinstance(starter["project"]["authors"], AoT)


# ---------------------------------------------------------------------------
# Versions and dependencies
# ---------------------------------------------------------------------------

_VERSIONS = """\
[project]
requires-python = ">={python}"

[tool.basedpyright]
pythonVersion = "{python}"

[tool.ruff]
target-version = "py{ruff}"

[tool.ty.environment]
python-version = "{python}"
"""


@pytest.mark.parametrize(
    ("project", "expected"), [("3.15", "3.15"), ("3.10", "3.11"), ("3.11", "3.11")]
)
def test_python_versions_take_the_highest(
    tmp_path: Path, project: str, expected: str
) -> None:
    """Each Python version key holds the higher of the two versions."""

    def versions(python: str) -> str:
        return _VERSIONS.format(python=python, ruff=python.replace(".", ""))

    merged = _merge(tmp_path, versions("3.11"), versions(project))

    assert merged == versions(expected)


def test_dependencies_merge_by_version_in_the_project_order(tmp_path: Path) -> None:
    """
    A higher template spec replaces the project's in place; missing ones follow.

    Each new dependency also loses its [toml] extra, which Python 3.11's tomllib
    made unnecessary.
    """
    template = """\
[project]
requires-python = ">=3.11"

[dependency-groups]
lint = ["alpha~=2.0", "beta~=1.0", "radon[toml]~=6.0", "zeta>=0.5"]
test = ["coverage[toml]~=7.0"]
"""
    project = """\
[dependency-groups]
lint = [
  "zeta>=1",
  # Pinned for a reason.
  "alpha~=1.0",
  "radon~=6.0",
]
test = []
"""

    merged = _merge(tmp_path, template, project)

    assert merged.endswith("""\
[dependency-groups]
lint = [
  "zeta>=1",
  # Pinned for a reason.
  "alpha~=2.0",
  "radon~=6.0",
  "beta~=1.0",
]
test = ["coverage~=7.0"]
""")


# ---------------------------------------------------------------------------
# Retirement
# ---------------------------------------------------------------------------


def test_remove_values_prunes_emptied_tables() -> None:
    """A table emptied by retirement goes; others, even empty ones, stay."""
    doc = tomlkit.parse("""\
[tool.a]
exclude = ["x"]

[tool.b]
exclude = ["x", "y"]

[tool.c]
""")
    retired = tomlkit.parse('[tool.a]\nexclude = ["x"]\n\n[tool.b]\nexclude = ["x"]\n')

    merge_toml.remove_values(doc, retired)

    assert tomlkit.dumps(doc) == '[tool.b]\nexclude = ["y"]\n\n[tool.c]\n'


def test_remove_values_prunes_emptied_parents() -> None:
    """A super table left with no tables goes with them."""
    doc = tomlkit.parse('[project]\nname = "x"\n\n[tool.a]\nexclude = ["x"]\n')
    retired = tomlkit.parse('[tool.a]\nexclude = ["x"]\n')

    merge_toml.remove_values(doc, retired)

    assert tomlkit.dumps(doc) == '[project]\nname = "x"\n\n'


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("project", ["", _EXISTING], ids=["empty", "existing"])
def test_a_second_merge_changes_nothing(tmp_path: Path, project: str) -> None:
    """merge(merge(x)) == merge(x), byte for byte."""
    path = tmp_path / "pyproject.toml"
    path.write_text(project)

    first = _update(path)

    assert _update(path) == first
