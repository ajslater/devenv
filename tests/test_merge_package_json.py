"""Tests for merging package.json files."""

import json
from pathlib import Path

import pytest

from scripts.merge_package_json import (
    deep_merge,
    extract_version_from_range,
    is_spec_unbounded,
    main,
    merge_dependency_specs,
    merge_script_entry,
)

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "merge" / "node_root" / "package.json"
_REMOVE_PACKAGES = _ROOT / "remove_node_packages.txt"
_REMOVE_VALUES = _ROOT / "merge" / "node_root" / "package.remove.json"
# A child project that has drifted from the template the ways real ones do.
_PROJECT = {
    "name": "demo",
    "version": "1.2.0",
    "private": True,
    "scripts": {
        "build": "vite build",
        "lint": "tsc --noEmit && eslint_d --cache . && prettier --check . && bin/remark-for-claude.sh",
    },
    "browserslist": ["defaults", "> 1%"],
    "prettier": {
        "plugins": ["prettier-plugin-svelte", "prettier-plugin-sh"],
        "overrides": [
            {"files": ["*.svelte"], "options": {"parser": "svelte"}},
            {"files": ["**/*Dockerfile"], "options": {"parser": "sh"}},
            {"files": ["**/*.xsd"], "options": {"printWidth": 120}},
        ],
    },
    "remarkConfig": {"plugins": ["gfm", "preset-prettier"]},
    "dependencies": {
        "lib": "workspace:*",
        "remark-cli": "^12.0.0",
        "svelte": "catalog:",
        "vite": "<7.0.0",
    },
    "devDependencies": {
        "eslint": "10.9.0",
        "eslint-plugin-unicorn": "^74.1.0",
        "local-config": "link:../config",
        "prettier": "^3.9.9",
        "remark-gfm": "^4.0.0",
    },
    "bundledDependencies": ["lib"],
}


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
        # An upper bound is no floor, wherever it sits in the range.
        ("<2.0.0", None),
        ("<=2.0.0", None),
        ("<9.5.0 >=9.0.0", "9.0.0"),
        ("<1.0.0 || >=2.0.0", "2.0.0"),
        # Specs with no version at all are unparsable.
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
        # Any protocol or path spec is opaque: kept as written, never compared.
        ("^3.6.2", "catalog:", "catalog:"),
        ("catalog:", "^3.6.2", "catalog:"),
        ("^3.6.2", "catalog:lint", "catalog:lint"),
        ("^1.0.0", "link:../pkg", "link:../pkg"),
        ("^1.0.0", "portal:../pkg", "portal:../pkg"),
        ("^1.0.0", "npm:other@^0.5.0", "npm:other@^0.5.0"),
        ("npm:other@^0.5.0", "^1.0.0", "npm:other@^0.5.0"),
        (
            "^1.0.0",
            "git://github.com/o/r.git#v0.5.0",
            "git://github.com/o/r.git#v0.5.0",
        ),
        ("^1.0.0", "o/r#v0.5.0", "o/r#v0.5.0"),
        # Between two opaque specs the later file's wins.
        ("workspace:*", "catalog:", "catalog:"),
        # An upper bound alone has no floor, so it loses to one that does.
        ("^1.0.0", "<2.0.0", "^1.0.0"),
        ("<2.0.0", "^1.0.0", "^1.0.0"),
        ("^1.0.0", "<=2.0.0", "^1.0.0"),
        (">=1.0.0 <2.0.0", "<3.0.0", ">=1.0.0 <2.0.0"),
        # Unparsable specs fall back to the update.
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

    merged = deep_merge(template, project)

    assert merged == {key: {"eslint-plugin-unicorn": ">=73.0.0"}}


def test_deep_merge_keeps_widest_peer_dependency_or_range() -> None:
    """
    A peerDependencies OR range keeps its newest major through the merge path.

    _deep_merge_value routes every key ending in "dependencies" through
    merge_dependencies, so the standard React peer range is merged, not copied.
    """
    template = {"peerDependencies": {"react": "^17.0.0"}}
    project = {"peerDependencies": {"react": "^16.0.0 || ^17.0.0 || ^18.0.0"}}

    merged = deep_merge(template, project)

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

    merged = deep_merge(template, project)

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

    merged = deep_merge({"plugins": [entry]}, {"plugins": [entry, "gfm"]})

    assert merged == {"plugins": ["gfm", entry]}


def test_deep_merge_list_orders_configured_entries_by_name() -> None:
    """Configured entries sort among themselves by plugin name."""
    template = {"plugins": [["lint-maximum-line-length", 80]]}
    project = {"plugins": [["lint-list-item-indent", "one"], "gfm"]}

    merged = deep_merge(template, project)

    assert merged == {
        "plugins": [
            "gfm",
            ["lint-list-item-indent", "one"],
            ["lint-maximum-line-length", 80],
        ]
    }


def test_deep_merge_list_strategy_replace() -> None:
    """--list-strategy replace keeps the later file's array as it is."""
    merged = deep_merge({"plugins": ["b", "c"]}, {"plugins": ["c", "a"]}, "replace")

    assert merged == {"plugins": ["c", "a"]}


@pytest.mark.parametrize("key", ["bundledDependencies", "bundleDependencies"])
def test_deep_merge_bundled_dependencies_array(key: str) -> None:
    """An array of bundled names merges as an array, not as a spec object."""
    merged = deep_merge({key: ["b"]}, {key: ["a", "b"]})

    assert merged == {key: ["a", "b"]}


def test_deep_merge_overrides_keep_their_order() -> None:
    """
    Prettier applies overrides in order, so the merge keeps it on every pass.

    The earlier file's entries come first, in its order, and win for the same
    files globs; the later file's new entries follow in its order.
    """
    md = {"files": ["**/*.md"], "options": {"proseWrap": "always"}}
    nginx = {"files": ["**/nginx/*.conf"], "options": {"parser": "nginx"}}
    xsd = {"files": ["**/*.xsd"], "options": {"printWidth": 120}}
    svelte = {"files": ["*.svelte"], "options": {"parser": "svelte"}}
    own_md = {"files": ["**/*.md"], "options": {"proseWrap": "never"}}
    template = {"prettier": {"overrides": [md, nginx, xsd]}}
    project = {"prettier": {"overrides": [svelte, own_md, xsd]}}

    merged = deep_merge(template, project)

    assert deep_merge(template, template) == template
    assert merged == {"prettier": {"overrides": [md, nginx, xsd, svelte]}}
    assert deep_merge(template, merged) == merged


@pytest.mark.parametrize(
    ("base", "update", "expected"),
    [
        # A project step before the template's survives and none duplicates.
        (
            "eslint_d --cache . && prettier --check .",
            "tsc --noEmit && eslint_d --cache .",
            "tsc --noEmit && eslint_d --cache . && prettier --check .",
        ),
        # The project's order wins over the template's.
        ("a && b", "b && a", "b && a"),
        # Template steps the project lacks follow its own, in template order.
        ("a && b && c", "x && b", "x && b && a && c"),
        # A project that repeats a step keeps every repeat.
        ("make", "cd a && make && cd b && make", "cd a && make && cd b && make"),
        ("a && b", "a && b", "a && b"),
        ("a && b", "", "a && b"),
    ],
)
def test_merge_script_entry(base: str, update: str, expected: str) -> None:
    """A script is an ordered union of its && commands, project first."""
    merged = merge_script_entry(base, update)

    assert merged == expected
    assert merge_script_entry(base, merged) == merged


def _update(project: Path) -> bytes:
    """Merge the template into project the way update_devenv does."""
    sources = [_TEMPLATE, project] if project.is_file() else [_TEMPLATE]
    argv = [*map(str, sources), "-o", str(project)]
    argv += ["--remove", str(_REMOVE_PACKAGES)]
    argv += ["--remove-values", str(_REMOVE_VALUES)]
    main(argv)
    return project.read_bytes()


@pytest.mark.parametrize(
    "seed", [None, "", json.dumps(_PROJECT, indent=2)], ids=["new", "empty", "real"]
)
def test_second_merge_is_a_fixed_point(tmp_path: Path, seed: str | None) -> None:
    """merge(merge(x)) == merge(x), byte for byte."""
    project = tmp_path / "package.json"
    if seed is not None:
        project.write_text(seed)

    first = _update(project)

    assert _update(project) == first


def test_merge_keeps_a_drifted_project_s_own_choices(tmp_path: Path) -> None:
    """The realistic project keeps its own steps, specs and overrides."""
    project = tmp_path / "package.json"
    project.write_text(json.dumps(_PROJECT))

    merged = json.loads(_update(project))

    assert merged["scripts"] == {
        "fix": "eslint_d --cache --fix . && prettier --write .",
        "lint": "tsc --noEmit && eslint_d --cache . && prettier --check .",
        "build": "vite build",
    }
    assert merged["dependencies"] == {
        "lib": "workspace:*",
        "svelte": "catalog:",
        "vite": "<7.0.0",
    }
    dev = merged["devDependencies"]
    assert dev["eslint"] == "^10.9.0"
    assert dev["eslint-plugin-unicorn"] == ">=74.0.0"
    assert dev["local-config"] == "link:../config"
    assert "remark-gfm" not in dev
    assert merged["bundledDependencies"] == ["lib"]
    assert "remarkConfig" not in merged
    files = [override["files"] for override in merged["prettier"]["overrides"]]
    assert files == [
        ["**/*.md"],
        ["**/nginx/http.d/**/*.conf"],
        ["**/*.xsd"],
        ["*.svelte"],
    ]


@pytest.mark.parametrize("text", ["", "\n"])
def test_empty_project_file_merges_as_an_empty_object(
    tmp_path: Path, text: str
) -> None:
    """A 0-byte package.json, as `touch` leaves it, is {} rather than an error."""
    project = tmp_path / "package.json"
    project.write_text(text)

    main([str(_TEMPLATE), str(project), "-o", str(project)])

    assert json.loads(project.read_text()) == json.loads(_TEMPLATE.read_text())
