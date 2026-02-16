#!/usr/bin/env python3
"""
Deep merge multiple package.json files into a single merged file.

This script recursively merges package.json files, with later files taking precedence
over earlier ones. Special handling for dependencies and devDependencies where
semver ranges are intelligently merged to prefer higher version constraints.

Requirements:
    pip install semantic-version
    Python 3.14+
"""

from __future__ import annotations

import argparse
import json
import re
from contextlib import suppress
from pathlib import Path
from types import MappingProxyType
from typing import Any

from semantic_version import NpmSpec, Version
from semantic_version.base import Range

DEPENDENCY_KEYS = frozenset(
    {
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "bundledDependencies",
        "bundleDependencies",
    }
)

# Prefix priority for npm version ranges (higher priority = more flexible)
# Priority: ^ (caret) > ~ (tilde) > >= > > > = (exact)
# Uses SimpleSpec class constants for operator keys
PREFIX_PRIORITY = MappingProxyType(
    {
        "^": 4,  # Caret range (most flexible, npm-specific)
        "~": 3,  # Tilde range (npm-specific)
        ">=": 2,  # Greater than or equal
        ">": 1,  # Greater than
        "=": 0,  # Exact (least flexible)
        "<=": 0,  # Less than or equal (treat as exact for priority)
        "<": 0,  # Less than (treat as exact for priority)
    }
)

# Special protocols that should not be parsed as semver
SPECIAL_PROTOCOLS = frozenset(
    {
        "workspace:",
        "git+",
        "http://",
        "https://",
        "file:",
        "github:",
    }
)


def normalize_npm_version(version_str: str) -> str:
    """
    Normalize npm version string for semantic-version parsing.

    Args:
        version_str: npm version string

    Returns:
        Normalized version string

    """
    # Handle special cases that semantic-version can't parse
    if version_str in ("*", "latest", "next", ""):
        return version_str

    # Handle special protocols
    if any(protocol in version_str for protocol in SPECIAL_PROTOCOLS):
        return version_str

    # Replace wildcards with actual 0s for parsing
    return version_str.replace("x", "0").replace("X", "0")


def get_version_prefix(version_str: str) -> str:
    """Extract the npm range prefix from a version string using regex."""
    # Order matters: >= and <= must come before > and
    match = re.match(r"^([\^~]|>=|<=|>|<|=)", version_str)
    if match:
        return match.group(1)
    return "="  # Default to exact match


def get_operator_from_range(spec: NpmSpec) -> str:
    """
    Extract the operator from the first Range object in the spec's clause structure.

    Returns the operator as a string matching PREFIX_PRIORITY keys.

    Args:
        spec: The NpmSpec object

    Returns:
        The operator string or "=" as default

    """
    try:
        if hasattr(spec, "clause") and spec.clause:
            clause = spec.clause

            # Find first Range object
            if isinstance(clause, Range):
                return clause.operator

            # Recursively search for Range objects
            def find_first_range(obj):
                if isinstance(obj, Range):
                    return obj
                if hasattr(obj, "__iter__") and not isinstance(obj, str):
                    for item in obj:
                        result = find_first_range(item)
                        if result:
                            return result
                return None

            first_range = find_first_range(clause)
            if first_range:
                return first_range.operator

    except (ValueError, AttributeError):
        pass

    return "="  # Default to exact match


def _search_spec_clause_for_version(spec):
    """Search the spec's clause structure for Range objects."""
    if not hasattr(spec, "clause") or not spec.clause:
        return None
    # The clause can be a single Range or a combination of Ranges
    clause = spec.clause

    # Extract Range and get its target version
    if (
        isinstance(clause, Range)
        and hasattr(clause, "target")
        and isinstance(clause.target, Version)
    ):
        return clause.target

    # Recursively search for the first Range object
    def find_first_range(obj):
        if isinstance(obj, Range):
            return obj
        if hasattr(obj, "__iter__") and not isinstance(obj, str):
            for item in obj:
                result = find_first_range(item)
                if result:
                    return result
        return None

    first_range = find_first_range(clause)
    if (
        first_range
        and hasattr(first_range, "target")
        and isinstance(first_range.target, Version)
    ):
        return first_range.target
    return None


def _extract_version_from_spec(spec: NpmSpec, original_str: str) -> Version | None:
    """
    Extract a Version object from an NpmSpec by traversing its clause structure.

    Searches for Range objects in the spec's clauses and extracts their target version.

    Args:
        spec: The NpmSpec object
        original_str: The original version string (for special case handling)

    Returns:
        Version object or None

    """
    # Handle special cases
    if original_str in ("*", "latest", "", "next"):
        return None

    # Handle special protocols
    if any(protocol in original_str for protocol in SPECIAL_PROTOCOLS):
        return None

    try:
        if version := _search_spec_clause_for_version(spec):
            return version
    except (ValueError, AttributeError):
        pass

    # Last resort: try to extract version using regex
    try:
        # Remove npm operators
        cleaned = re.sub(r"^[\^~>=<]+", "", original_str)

        # Handle OR ranges - take the first one
        if "||" in cleaned:
            cleaned = cleaned.split("||")[0].strip()

        # Handle hyphen ranges - take the first version
        if " - " in cleaned:
            cleaned = cleaned.split(" - ")[0].strip()

        # Take first space-separated token
        cleaned = cleaned.split()[0].strip() if " " in cleaned else cleaned.strip()

        # Replace wildcards
        cleaned = cleaned.replace("x", "0").replace("X", "0")

        # Try to parse as a version
        return Version(cleaned)

    except (ValueError, AttributeError):
        pass

    return None


def compare_npm_specs(base_version: str, update_version: str) -> int:
    """
    Compare two npm version specifications by testing which allows higher versions.

    Compares NpmSpec clauses to determine which specification is more permissive.
    Tests progressively higher versions to see which spec accepts them.

    Args:
        base_version: Base version string
        update_version: Update version string

    Returns:
        1 if update allows higher versions, -1 if base allows higher, 0 if equal

    """
    try:
        # Parse as NpmSpec - create these objects once
        base_spec = NpmSpec(normalize_npm_version(base_version))
        update_spec = NpmSpec(normalize_npm_version(update_version))

        # Extract base versions to use as starting points for testing
        base_ver = _extract_version_from_spec(base_spec, base_version)
        update_ver = _extract_version_from_spec(update_spec, update_version)

        # If we can't extract versions, compare as equal
        if base_ver is None and update_ver is None:
            return 0
        if base_ver is None:
            return 1
        if update_ver is None:
            return -1

        # First check: if the base versions are different, prefer the higher one
        if update_ver > base_ver:
            return 1
        if base_ver > update_ver:
            return -1

        # If both specs accept the same test versions, they're equally permissive

    except (ValueError, AttributeError):
        # If spec creation or testing fails, return equal as safe default
        pass
    return 0


def merge_dependency_versions(base_version: str, update_version: str) -> str:
    """
    Merge two npm semver version strings, preferring the higher version.

    Uses semantic-version package for proper npm version specification comparison.
    When versions are equal, prefers more flexible range operators based on
    PREFIX_PRIORITY.

    Args:
        base_version: Base version string
        update_version: Update version string

    Returns:
        The version string with the higher constraint

    """
    # Handle special cases
    if base_version in ("*", "latest") and update_version not in ("*", "latest"):
        return update_version
    if update_version in ("*", "latest") and base_version not in ("*", "latest"):
        return base_version

    # Handle special protocols - prefer update
    if any(protocol in base_version for protocol in SPECIAL_PROTOCOLS) or any(
        protocol in update_version for protocol in SPECIAL_PROTOCOLS
    ):
        return update_version

    # Compare versions
    comparison = compare_npm_specs(base_version, update_version)

    if comparison > 0:
        return update_version
    if comparison < 0:
        return base_version

    # Versions are equal, prefer more flexible range
    # Use PREFIX_PRIORITY to determine flexibility
    try:
        base_spec = NpmSpec(normalize_npm_version(base_version))
        update_spec = NpmSpec(normalize_npm_version(update_version))

        # Get operators from Range objects in the specs
        base_operator = get_operator_from_range(base_spec)
        update_operator = get_operator_from_range(update_spec)

        # Handle caret (^) and tilde (~) specially as they're npm-specific
        base_prefix = get_version_prefix(base_version)
        update_prefix = get_version_prefix(update_version)

        # Use the prefix if it's ^ or ~, otherwise use the operator from Range
        base_op = base_prefix if base_prefix in ("^", "~") else base_operator
        update_op = update_prefix if update_prefix in ("^", "~") else update_operator

        base_priority = PREFIX_PRIORITY.get(base_op, 0)
        update_priority = PREFIX_PRIORITY.get(update_op, 0)

        result = update_version if update_priority > base_priority else base_version
    except (ValueError, AttributeError):
        # If we can't determine operators, prefer update as safe default
        result = update_version
    return result


def merge_dependencies(base: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """
    Merge two dependency dictionaries with semver-aware version selection.

    Args:
        base: Base dependencies
        updates: Update dependencies

    Returns:
        Merged dependencies with higher versions preferred

    """
    result = base.copy()

    for package, version in updates.items():
        if package in result:
            # Merge versions, preferring higher
            result[package] = merge_dependency_versions(result[package], version)
        else:
            # New package
            result[package] = version

    return result


def _deep_merge_value(
    key: str,
    value: Any,
    result: dict[Any, Any],
    list_strategy: str,
) -> None:
    if key not in result:
        # New key - just add it
        result[key] = value
        return

    base_val = result[key]

    # Special handling for dependency objects
    if key in DEPENDENCY_KEYS:
        result[key] = merge_dependencies(base_val, value)

    # Both values are dictionaries - recurse
    elif isinstance(base_val, dict) and isinstance(value, dict):
        result[key] = deep_merge(base_val, value, list_strategy)

    # Both values are lists - apply strategy
    elif isinstance(base_val, list) and isinstance(value, list):
        if list_strategy == "merge":
            if key == "overrides":
                # Special handling for overrides: deduplicate by "files" key
                # Prioritize base values when there are duplicates
                dedup_dict: dict[str, Any] = {}

                # Add base items first (these take priority)
                for item in base_val:
                    if isinstance(item, dict) and "files" in item:
                        dedup_key = ":".join(sorted(item["files"]))
                        dedup_dict[dedup_key] = item

                # Add update items only if not already present
                for item in value:
                    if isinstance(item, dict) and "files" in item:
                        dedup_key = ":".join(sorted(item["files"]))
                        if dedup_key not in dedup_dict:
                            dedup_dict[dedup_key] = item

                dedup_dict = dict(sorted(dedup_dict.items()))

                result[key] = list(dedup_dict.values())
            else:
                # Regular list merging with deduplication and sorting
                merged_list = base_val + value
                # Try to deduplicate if possible (for hashable types)
                with suppress(TypeError):
                    merged_list = list(set(merged_list))
                result[key] = sorted(merged_list)
        else:
            result[key] = value

    # Otherwise, the new value overwrites the old
    else:
        result[key] = value


def deep_merge(
    base: dict[Any, Any], updates: dict[Any, Any], list_strategy: str = "replace"
) -> dict[Any, Any]:
    """
    Recursively merge two dictionaries.

    Special handling for dependency keys where semver versions are compared.

    Args:
        base: The base dictionary to merge into
        updates: The dictionary with updates to apply
        list_strategy: How to handle lists - 'replace' (default) or 'merge'

    Returns:
        The merged dictionary

    """
    result = base.copy()
    for key, value in updates.items():
        _deep_merge_value(key, value, result, list_strategy)
    return result


def load_package_json(filepath: Path) -> dict[Any, Any]:
    """
    Load a package.json file and return its contents.

    Args:
        filepath: Path to the package.json file

    Returns:
        The parsed JSON content as a dictionary

    """
    content = json.loads(filepath.read_text())
    if not isinstance(content, dict):
        reason = f"{filepath} does not contain a JSON object at root level"
        raise TypeError(reason)
    return content


def merge_package_json_files(
    filepaths: list[Path], list_strategy: str = "replace"
) -> dict[Any, Any]:
    """
    Merge multiple package.json files in order.

    Args:
        filepaths: List of paths to package.json files (in order of precedence)
        list_strategy: How to handle lists - 'replace' or 'merge'

    Returns:
        The merged dictionary

    """
    if not filepaths:
        return {}

    # Start with the first file
    result = load_package_json(filepaths[0])

    # Merge in each subsequent file
    for filepath in filepaths[1:]:
        updates = load_package_json(filepath)
        result = deep_merge(result, updates, list_strategy)

    return result


def main() -> None:
    """
    Run cli.

    Parses command-line arguments, validates input files, performs the merge
    with semver-aware dependency handling, and outputs the result to stdout or a file.
    """
    parser = argparse.ArgumentParser(
        description="Deep merge multiple package.json files with semver-aware dependency merging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge three files, output to stdout
  %(prog)s package.json package-override.json package-local.json

  # Merge and save to output file
  %(prog)s package.json package-dev.json -o package-merged.json

  # Merge with array appending instead of replacement
  %(prog)s package.json package-extra.json --list-strategy merge

Dependency Merging:
  For dependencies, devDependencies, and related keys, the tool compares
  semver version strings and keeps the higher version constraint.

  Example:
    base:    "express": "^4.17.1"
    update:  "express": "^4.18.0"
    result:  "express": "^4.18.0"

    base:    "react": "~16.8.0"
    update:  "react": "^17.0.0"
    result:  "react": "^17.0.0"
        """,
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="package.json files to merge (in order of precedence - later files override earlier ones)",
    )

    parser.add_argument(
        "-o", "--output", type=Path, help="Output file path (default: stdout)"
    )

    parser.add_argument(
        "--list-strategy",
        choices=["merge", "replace"],
        default="merge",
        help="How to handle array merging: replace or merge (default)",
    )

    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces for JSON indentation (default: 2)",
    )

    args = parser.parse_args()

    # Validate input files exist
    for filepath in args.files:
        if not filepath.exists():
            reason = f"File not found: {filepath}"
            parser.error(reason)

    # Perform the merge
    merged_data = merge_package_json_files(args.files, args.list_strategy)

    # Output the result
    json_output = json.dumps(merged_data, indent=args.indent, ensure_ascii=False)
    json_output += "\n"  # Add trailing newline like npm does

    if args.output:
        args.output.write_text(json_output)
        print(f"Merged package.json written to: {args.output}")  # noqa: T201
    else:
        print(json_output)  # noqa: T201


if __name__ == "__main__":
    main()
