"""merge_toml's array merge."""

from __future__ import annotations

import tomlkit

from scripts import merge_toml


def test_merged_arrays_hold_each_value_once() -> None:
    """A value repeated in either file, or in both, appears once."""
    base = tomlkit.parse('[tool.x]\nexclude = ["b", "a", "b"]\n')
    update = tomlkit.parse('[tool.x]\nexclude = ["c", "a", "c"]\n')

    merged = merge_toml.deep_merge_tomlkit(base, update, "merge")

    assert merged["tool"]["x"]["exclude"] == ["a", "b", "c"]
