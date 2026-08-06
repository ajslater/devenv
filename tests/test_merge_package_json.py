"""Tests for semver-aware dependency spec merging."""

import pytest

from scripts.merge_package_json import is_spec_unbounded, merge_dependency_specs


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
