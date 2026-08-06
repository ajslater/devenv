"""Tests for semver-aware dependency spec merging."""

from argparse import Namespace

import pytest

from scripts.merge_package_json import (
    deep_merge,
    is_spec_unbounded,
    merge_dependency_specs,
)


@pytest.mark.parametrize(
    ("spec", "unbounded"),
    [
        (">=72.0", True),
        (">=72.0.0", True),
        (">72.0", True),
        (">= 72.0", True),
        ("^72.0.0", False),
        ("~72.0.0", False),
        ("72.0.0", False),
        (">=72.0 <80.0", False),
        (">=72.0 || >=80.0", False),
        ("<=72.0", False),
        ("*", False),
    ],
)
def test_is_spec_unbounded(spec: str, *, unbounded: bool) -> None:
    """Bare > and >= ranges are unbounded; everything else is not."""
    assert is_spec_unbounded(spec) == unbounded


@pytest.mark.parametrize(
    ("base", "update", "expected"),
    [
        # Higher version wins between bounded ranges.
        ("^4.17.1", "^4.18.0", "^4.18.0"),
        ("^4.18.0", "^4.17.1", "^4.18.0"),
        ("~16.8.0", "^17.0.0", "^17.0.0"),
        # An unbounded range beats a bounded range with an equal floor.
        (">=72.0", "^72.0.0", ">=72.0"),
        ("^72.0.0", ">=72.0", ">=72.0"),
        # An unbounded range beats a bounded range with a higher floor.
        (">=72.0", "^73.1.0", ">=72.0"),
        ("^73.1.0", ">=72.0", ">=72.0"),
        # Two unbounded ranges keep the higher floor.
        (">=72.0", ">=73.0.0", ">=73.0.0"),
        (">=73.0.0", ">=72.0", ">=73.0.0"),
        # Two unbounded ranges at the same floor keep the inclusive one.
        (">=72.0.0", ">72.0.0", ">=72.0.0"),
        (">72.0.0", ">=72.0.0", ">=72.0.0"),
        # A compound range is bounded, so it never wins on unboundedness.
        ("^73.1.0", ">=72.0 <73.0", "^73.1.0"),
        (">=72.0 <73.0", "^73.1.0", "^73.1.0"),
        # At equal floors a broader ^ or ~ beats a narrower compound range.
        ("^9.0.0", ">=9.0.0 <9.5.0", "^9.0.0"),
        (">=9.0.0 <9.5.0", "^9.0.0", "^9.0.0"),
        ("~3.3.0", ">=3.3.0 <3.3.2", "~3.3.0"),
        ("^1.0.0", ">1.0.0 <1.2.0", "^1.0.0"),
        # Equal versions prefer the more flexible bounded prefix.
        ("72.0.0", "^72.0.0", "^72.0.0"),
        ("~72.0.0", "^72.0.0", "^72.0.0"),
        # Special protocols always win.
        (
            "git+https://example.com/repo.git",
            "^1.0.0",
            "git+https://example.com/repo.git",
        ),
        ("^1.0.0", "workspace:*", "workspace:*"),
        # Unparseable specs fall back to the update.
        ("*", "latest", "latest"),
        ("*", "^1.0.0", "^1.0.0"),
        ("^1.0.0", "latest", "^1.0.0"),
    ],
)
def test_merge_dependency_specs(base: str, update: str, expected: str) -> None:
    """Merging prefers the spec that admits the highest versions."""
    assert merge_dependency_specs(base, update) == expected


@pytest.mark.parametrize("key", ["dependencies", "devDependencies", "peerDependencies"])
def test_deep_merge_preserves_unbounded_template_spec(key: str) -> None:
    """
    The template's unbounded spec survives the full merge path.

    update_devenv.py passes the devenv template as base and the project's own
    package.json as update, so a project pinned by `bun update` to a caret
    range must not clobber the template's deliberate `>=`.
    """
    template = {key: {"eslint-plugin-unicorn": ">=73.0.0"}}
    project = {key: {"eslint-plugin-unicorn": "^73.1.0"}}
    args = Namespace(remove_packages=frozenset())

    merged = deep_merge(template, project, args)

    assert merged == {key: {"eslint-plugin-unicorn": ">=73.0.0"}}
