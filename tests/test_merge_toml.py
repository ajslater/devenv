"""merge_toml's array merge."""

from __future__ import annotations

import re
from pathlib import Path

import tomlkit

from scripts import merge_toml

_PYPROJECT_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "merge"
    / "python"
    / "pyproject-template.toml"
)


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


def test_merged_arrays_hold_each_value_once() -> None:
    """A value repeated in either file, or in both, appears once."""
    base = tomlkit.parse('[tool.x]\nexclude = ["b", "a", "b"]\n')
    update = tomlkit.parse('[tool.x]\nexclude = ["c", "a", "c"]\n')

    merged = merge_toml.deep_merge_tomlkit(base, update, "merge")

    assert merged["tool"]["x"]["exclude"] == ["a", "b", "c"]
