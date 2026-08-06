"""Tests for semver-aware dependency spec merging."""

from argparse import Namespace

import pytest

from scripts.merge_package_json import (
    deep_merge,
    extract_version_from_range,
    is_spec_unbounded,
    merge_dependency_specs,
)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        # Plain ranges reduce to their floor.
        ("^1.2.3", "1.2.3"),
        ("~1.2.3", "1.2.3"),
        ("1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        (">= 72.0", "72.0.0"),
        ("1", "1.0.0"),
        # Wildcards fill in as zeros.
        ("1.x", "1.0.0"),
        ("1.X", "1.0.0"),
        ("1.*", "1.0.0"),
        # Compound and hyphen ranges use their leftmost comparator.
        (">=9.0.0 <9.5.0", "9.0.0"),
        ("1.2.3 - 2.3.4", "1.2.3"),
        # An OR range is ranked by its highest branch, not its first.
        ("^16.0.0 || ^17.0.0 || ^18.0.0", "18.0.0"),
        ("1.x || 2.x", "2.0.0"),
        ("^18.0.0 || ^16.0.0", "18.0.0"),
        # Dotted prerelease counters survive intact.
        ("^2.0.0-beta.1", "2.0.0-beta.1"),
        ("^2.0.0-beta.10", "2.0.0-beta.10"),
        ("~14.3.0-next.53", "14.3.0-next.53"),
        # Operator and wildcard letters inside a prerelease are not rewritten.
        ("^1.0.0-v10", "1.0.0-v10"),
        ("^1.0.0-next.x", "1.0.0-next.x"),
        ("1.2.3+build.5", "1.2.3+build.5"),
        # Specs with no version at all are unparseable.
        ("*", None),
        ("latest", None),
        ("next", None),
        ("", None),
    ],
)
def test_extract_version_from_range(spec: str, expected: str | None) -> None:
    """Ranges reduce to the semver floor of the branch admitting the most."""
    assert extract_version_from_range(spec) == expected


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
        # An OR range keeps its newest major instead of being ranked by its
        # lowest branch, in either argument order.
        (
            "^17.0.0",
            "^16.0.0 || ^17.0.0 || ^18.0.0",
            "^16.0.0 || ^17.0.0 || ^18.0.0",
        ),
        (
            "^16.0.0 || ^17.0.0 || ^18.0.0",
            "^17.0.0",
            "^16.0.0 || ^17.0.0 || ^18.0.0",
        ),
        ("1.x || 2.x", "^1.5.0", "1.x || 2.x"),
        ("^1.5.0", "1.x || 2.x", "1.x || 2.x"),
        # A dotted prerelease counter is compared, not truncated away.
        ("^2.0.0-beta.1", "^2.0.0-beta.10", "^2.0.0-beta.10"),
        ("^2.0.0-beta.10", "^2.0.0-beta.1", "^2.0.0-beta.10"),
        ("^1.0.0-rc.1", "^1.0.0-rc.4", "^1.0.0-rc.4"),
        ("^1.0.0-rc.4", "^1.0.0-rc.1", "^1.0.0-rc.4"),
        ("~14.3.0-next.9", "~14.3.0-next.53", "~14.3.0-next.53"),
        # Prerelease identifiers keep their v and x letters, so semver's
        # alphanumeric-beats-numeric ordering still applies.
        ("^1.0.0-v10", "^1.0.0-beta", "^1.0.0-v10"),
        ("^1.0.0-beta", "^1.0.0-v10", "^1.0.0-v10"),
        ("^1.0.0-next.x", "^1.0.0-next.1", "^1.0.0-next.x"),
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


def test_deep_merge_keeps_widest_peer_dependency_or_range() -> None:
    """
    A peerDependencies OR range keeps its newest major through the merge path.

    _deep_merge_value routes every key ending in "dependencies" through
    merge_dependencies, so the standard React peer range is merged, not copied.
    """
    template = {"peerDependencies": {"react": "^17.0.0"}}
    project = {"peerDependencies": {"react": "^16.0.0 || ^17.0.0 || ^18.0.0"}}
    args = Namespace(remove_packages=frozenset())

    merged = deep_merge(template, project, args)

    assert merged == {"peerDependencies": {"react": "^16.0.0 || ^17.0.0 || ^18.0.0"}}


def test_deep_merge_list_of_mixed_plugin_forms() -> None:
    """
    A [name, options] plugin entry merges alongside bare plugin names.

    remarkConfig.plugins holds both forms, so the merged list must not compare
    list to str, and the configured entry must stay after the presets it
    overrides or the disabling `false` is undone by preset-lint-recommended.
    """
    template = {"remarkConfig": {"plugins": ["gfm", "preset-lint-recommended"]}}
    project = {
        "remarkConfig": {
            "plugins": [
                "gfm",
                ["lint-no-duplicate-headings", False],
                "lint-no-duplicate-headings-in-section",
            ]
        }
    }
    args = Namespace(remove_packages=frozenset())

    merged = deep_merge(template, project, args, "merge")

    assert merged == {
        "remarkConfig": {
            "plugins": [
                "gfm",
                "lint-no-duplicate-headings-in-section",
                "preset-lint-recommended",
                ["lint-no-duplicate-headings", False],
            ]
        }
    }


def test_deep_merge_list_dedupes_unhashable_entries() -> None:
    """Identical [name, options] entries collapse to one."""
    entry = ["lint-maximum-line-length", 80]
    args = Namespace(remove_packages=frozenset())

    merged = deep_merge(
        {"plugins": [entry]}, {"plugins": [entry, "gfm"]}, args, "merge"
    )

    assert merged == {"plugins": ["gfm", entry]}


def test_deep_merge_list_orders_configured_entries_by_name() -> None:
    """Configured entries sort among themselves by plugin name."""
    args = Namespace(remove_packages=frozenset())
    template = {"plugins": [["lint-maximum-line-length", 80]]}
    project = {"plugins": [["lint-list-item-indent", "one"], "gfm"]}

    merged = deep_merge(template, project, args, "merge")

    assert merged == {
        "plugins": [
            "gfm",
            ["lint-list-item-indent", "one"],
            ["lint-maximum-line-length", 80],
        ]
    }
