#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "packaging>=26.0",
#   "tomlkit~=0.14",
# ]
# ///
"""
Deep merge TOML files into the last one, keeping its layout.

The last file, a project's own pyproject.toml, is the base: its values, key
order, comments and formatting stay. Each earlier file, a devenv template,
only fills in what the files after it lack, so a later file wins where both
hold a value. A key the base lacks goes beside its neighbours in the template.
Where both files hold a key:

- Tables merge recursively.
- Arrays keep the later file's items in order and append the earlier file's
  items it lacks, or with --list-strategy replace stay as the later file has
  them. An array of tables is always the later file's.
- Python dependency lists always merge by package, keeping the higher version.
- Python version keys keep the higher version.
- The comma-delimited strings at COMMA_LIST_KEY_PATHS merge like arrays.
- Any other value is the later file's.

Once requires-python is 3.11 or more, dependencies lose their [toml] extra.
"""

from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version
from tomlkit import TOMLDocument
from tomlkit.container import Container
from tomlkit.items import AbstractTable, AoT, Array, InlineTable, String, Table

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from packaging.specifiers import SpecifierSet

PYTHON_DEP_KEY_PATH_LEN = 2
DEP_KEY_PATHS = frozenset({("project", "dependencies"), ("build-system", "requires")})

REQUIRES_PYTHON_KEY_PATH = ("project", "requires-python")
BASEDPYRIGHT_VERSION_KEY_PATH = ("tool", "basedpyright", "pythonVersion")
TY_ENVIRONMENT_KEY_PATH = ("tool", "ty", "environment", "python-version")
RUFF_TARGET_VERSION_KEY_PATH = ("tool", "ruff", "target-version")
VERSION_KEY_PATHS = frozenset(
    {
        REQUIRES_PYTHON_KEY_PATH,
        BASEDPYRIGHT_VERSION_KEY_PATH,
        TY_ENVIRONMENT_KEY_PATH,
        RUFF_TARGET_VERSION_KEY_PATH,
    }
)
# Strings the tools read as comma-delimited lists. Any other string is a plain
# value, even one with commas, such as a description.
COMMA_LIST_KEY_PATHS: Final = frozenset(
    {
        ("tool", "codespell", "builtin"),
        ("tool", "codespell", "ignore-words-list"),
        ("tool", "codespell", "skip"),
        ("tool", "radon", "exclude"),
    }
)
LIST_STRATEGIES: Final = ("merge", "replace")

REQUIRES_PYTHON_PREFIX = ">="
RUFF_TARGET_PREFIX = "py"
MIN_PYTHON_VERSION_FOR_BUILTIN_TOML = Version("3.11")
TOML_EXTRA = "toml"


def parse_comma_delimited(value: str) -> list[str]:
    """Parse a comma-delimited string into a list of trimmed strings."""
    return [item.strip() for item in str(value).split(",") if item.strip()]


def merge_comma_delimited_strings(base_value: str, update_value: str) -> str:
    """
    Append base's items that update lacks to update's comma-delimited list.

    Returns update_value itself, layout and all, when it lacks none.
    """
    items = parse_comma_delimited(update_value)
    missing = [
        item
        for item in dict.fromkeys(parse_comma_delimited(base_value))
        if item not in items
    ]
    if not missing:
        return update_value
    return ",".join((*items, *missing))


def _parse_version_from_requires_python(value: str) -> Version | None:
    """Parse version from a >=X.Y format string."""
    stripped = str(value).strip()
    if stripped.startswith(REQUIRES_PYTHON_PREFIX):
        try:
            return Version(stripped[len(REQUIRES_PYTHON_PREFIX) :])
        except InvalidVersion:
            return None
    return None


def _parse_version_from_ruff_target(value: str) -> Version | None:
    """Parse version from pyXYZ format (e.g., py310 -> 3.10, py312 -> 3.12)."""
    stripped = str(value).strip()
    if stripped.startswith(RUFF_TARGET_PREFIX) and len(stripped) > len(
        RUFF_TARGET_PREFIX
    ):
        digits = stripped[len(RUFF_TARGET_PREFIX) :]
        if len(digits) >= 2:  # noqa: PLR2004
            version_str = f"{digits[0]}.{digits[1:]}"
            try:
                return Version(version_str)
            except InvalidVersion:
                return None
    return None


def _parse_bare_version(value: str) -> Version | None:
    """Parse a bare version string like 3.10 or 3.12."""
    try:
        return Version(str(value).strip())
    except InvalidVersion:
        return None


def _merge_version_values(
    base_value: Any, update_value: Any, key_path: tuple[str, ...]
) -> Any:
    """
    Return the value of the two that names the higher Python version.

    Dispatches to the appropriate parser based on the key path. Keeps the
    update value on a tie or when either fails to parse.
    """
    if key_path == REQUIRES_PYTHON_KEY_PATH:
        parse = _parse_version_from_requires_python
    elif key_path == RUFF_TARGET_VERSION_KEY_PATH:
        parse = _parse_version_from_ruff_target
    else:
        parse = _parse_bare_version
    base_ver = parse(str(base_value))
    update_ver = parse(str(update_value))
    if base_ver and update_ver and base_ver > update_ver:
        return base_value
    return update_value


def is_python_dependency_key(key_path: tuple[str, ...]) -> bool:
    """
    Check if a key path represents a Python dependency list.

    Handles:
    - project.dependencies
    - dependency-groups.* (any subkey)
    - build-system.requires

    Args:
        key_path: Tuple of keys representing the path (e.g., ('project', 'dependencies'))

    Returns:
        True if this is a Python dependency list

    """
    return len(key_path) == PYTHON_DEP_KEY_PATH_LEN and (
        key_path in DEP_KEY_PATHS or key_path[0] == "dependency-groups"
    )


def parse_python_requirement(dep_string: str) -> tuple[str, SpecifierSet | None]:
    """
    Parse a Python dependency string into package name and version specifiers.

    Args:
        dep_string: A PEP 508 dependency string (e.g., "requests>=2.28.0")

    Returns:
        Tuple of (package_name, specifier_set) or (package_name, None) if no version

    """
    try:
        req = Requirement(dep_string.strip())
        return req.name.lower(), req.specifier or None
    except InvalidRequirement:
        # If parsing fails, try to extract just the package name
        # Handle simple cases like "package-name" without version
        if match := re.match(r"^([a-zA-Z0-9._-]+)", dep_string.strip()):
            return match.group(1).lower(), None
        # If all else fails, return the string as-is
        return dep_string.strip().lower(), None


def get_max_version_from_specifier(spec: SpecifierSet) -> Version | None:
    """
    Extract the maximum/preferred version from a specifier set.

    For comparison purposes, we extract a representative version:
    - For >=x.y.z, use x.y.z
    - For ==x.y.z, use x.y.z
    - For ~=x.y.z, use x.y.z
    - For <x.y.z, use a version slightly less
    - For complex specs, try to find the highest lower bound

    Args:
        spec: A SpecifierSet from packaging

    Returns:
        A representative Version or None

    """
    if not spec:
        return None

    versions: list[Version] = []
    for s in spec:
        # Extract version from the specifier
        try:
            ver = Version(s.version)
            # Prefer lower bounds (>=, ==, ~=) over upper bounds
            if s.operator in (">=", "==", "~=", ">"):
                versions.append(ver)
            elif s.operator in ("<=", "<"):
                # Upper bounds are less preferred
                versions.append(ver)
        except InvalidVersion:
            continue

    return max(versions) if versions else None


def _base_spec_wins(base_spec, update_spec) -> bool:
    """Return whether a dependency's base spec replaces its update spec."""
    # Prefer a spec with a version to one without.
    if base_spec is None or update_spec is None:
        return update_spec is None and base_spec is not None
    base_ver = get_max_version_from_specifier(base_spec)
    update_ver = get_max_version_from_specifier(update_spec)
    if base_ver and update_ver:
        return base_ver > update_ver
    # Only a comparable base version beats an incomparable update.
    return bool(base_ver) and not update_ver


def merge_python_dependencies(base: Iterable[Any], updates: list[Any]) -> None:
    """
    Merge base's dependencies into the updates list, in place.

    A base spec with a higher version replaces the update's where it stands,
    and a package that updates lacks is appended, so updates keeps its order,
    formatting and comments.
    """
    names = [parse_python_requirement(str(dep))[0] for dep in updates]
    for dep in base:
        name, base_spec = parse_python_requirement(str(dep))
        if name not in names:
            updates.append(str(dep))
            names.append(name)
            continue
        index = names.index(name)
        _, update_spec = parse_python_requirement(str(updates[index]))
        if _base_spec_wins(base_spec, update_spec):
            updates[index] = str(dep)


def _is_table_like(value: Any) -> bool:
    """Check if a value is a table-like tomlkit structure."""
    return isinstance(value, dict | Table | InlineTable | TOMLDocument)


def _holds_tables(array: Iterable[Any]) -> bool:
    """Check if an array is an array of tables, inline or [[headed]]."""
    return isinstance(array, AoT) or any(_is_table_like(item) for item in array)


def _merge_arrays(
    base_value: list[Any],
    update_value: list[Any],
    list_strategy: str,
    key_path: tuple[str, ...] = (),
) -> list[Any]:
    """
    Merge base's array into update's, in place, and return it.

    Dependency lists merge by package and version. Otherwise, with the merge
    strategy, base's values that update lacks are appended, so update keeps its
    order and its own repeats. An array of tables stays update's.
    """
    if is_python_dependency_key(key_path):
        merge_python_dependencies(base_value, update_value)
    elif list_strategy == "merge" and not (
        _holds_tables(base_value) or _holds_tables(update_value)
    ):
        for item in base_value:
            if item not in update_value:
                update_value.append(item)
    return update_value


def _merge_value_pair(
    base_value: Any, update_value: Any, list_strategy: str, key_path: tuple[str, ...]
) -> Any:
    """
    Return the merged value of a key that both structures hold.

    Args:
        base_value: The earlier file's value
        update_value: The later file's value, which wins ties
        list_strategy: How to handle lists - 'merge' or 'replace'
        key_path: The path to this key for detecting special merge behavior

    Returns:
        update_value, merged in place, or the value that replaces it

    """
    if key_path in VERSION_KEY_PATHS:
        return _merge_version_values(base_value, update_value, key_path)
    if _is_table_like(base_value) and _is_table_like(update_value):
        return deep_merge_tomlkit(base_value, update_value, list_strategy, key_path)
    if (
        key_path in COMMA_LIST_KEY_PATHS
        and list_strategy == "merge"
        and isinstance(base_value, str)
        and isinstance(update_value, str)
    ):
        return merge_comma_delimited_strings(base_value, update_value)
    if isinstance(base_value, list) and isinstance(update_value, list):
        return _merge_arrays(base_value, update_value, list_strategy, key_path)
    return update_value


def _item(table: Any, key: str) -> Any:
    """Return table's item at key, keeping a boolean's comment."""
    if isinstance(table, Container | AbstractTable):
        return table.item(key)
    return table[key]


def _neighbour_position(
    container: Container, key: str, keys: list[str], *, is_table: bool
) -> int | None:
    """
    Return where key goes in container, beside its nearest neighbour in keys.

    That is just after the nearest key before it, or just before the nearest
    key after it, that container holds. A neighbour must be of the same kind,
    a table or a plain value, because a value placed after a [header] would
    belong to that table.
    """
    index = keys.index(key)
    neighbours = [(name, 1) for name in reversed(keys[:index])]
    neighbours += [(name, 0) for name in keys[index + 1 :]]
    for name, after in neighbours:
        spots = [
            spot
            for spot, (body_key, item) in enumerate(container.body)
            if body_key is not None
            and body_key.key == name
            and isinstance(item, Table | AoT) == is_table
        ]
        if spots:
            return max(spots) + 1 if after else min(spots)
    return None


def _insert(updates: Any, key: str, value: Any, keys: list[str]) -> None:
    """
    Add key to updates beside its neighbours in keys, the base's key order.

    Without a neighbour, tomlkit appends it: a plain value after the other
    plain values and a table after the other tables.
    """
    container = updates.value if isinstance(updates, Table) else updates
    if isinstance(container, Container):
        is_table = isinstance(value, Table | AoT)
        position = _neighbour_position(container, key, keys, is_table=is_table)
        if position is not None and position < len(container.body):
            container._insert_at(position, key, value)  # noqa: SLF001
            return
    updates[key] = value


def deep_merge_tomlkit(
    base: Any,
    updates: Any,
    list_strategy: str = "merge",
    key_path: tuple[str, ...] = (),
) -> Any:
    """
    Merge base into updates, in place, and return updates.

    updates is the later file, so its values win and its order, comments and
    layout stay. base only fills in what updates lacks.

    Args:
        base: The earlier file's tomlkit structure
        updates: The later file's tomlkit structure, merged in place
        list_strategy: How to handle lists - 'merge' (default) or 'replace'
        key_path: Current path in the document (for detecting special keys)

    Returns:
        updates

    """
    if not (_is_table_like(base) and _is_table_like(updates)):
        return updates

    keys = list(base.keys())
    for key in keys:
        base_value = _item(base, key)
        if key not in updates:
            _insert(updates, key, copy.deepcopy(base_value), keys)
            continue
        update_value = updates[key]
        merged = _merge_value_pair(
            base_value, update_value, list_strategy, (*key_path, key)
        )
        if merged is not update_value:
            updates[key] = merged
    return updates


def _last_item_group(array: Array) -> Any:
    """Return tomlkit's private group for array's last item, which holds its comma."""
    return array._value[array._index_map[len(array) - 1]]  # noqa: SLF001


def _remove_array_items(array: Array, drop: frozenset[str]) -> None:
    """
    Remove drop's items from array, keeping whether it ends in a comma.

    tomlkit leaves a comma after the new last item when it deletes a multiline
    array's last item, and prettier-plugin-toml keeps that comma as a request
    to keep the array expanded.
    """
    comma = _last_item_group(array).comma if array else None
    for index in reversed(range(len(array))):
        if str(array[index]) in drop:
            del array[index]
    if array:
        _last_item_group(array).comma = comma


def _remove_items(doc: Any, key: str, drop: frozenset[str]) -> None:
    """
    Remove drop's items from the array or comma-delimited string at doc[key].

    Drops the key itself once nothing is left.
    """
    target = doc[key]
    if isinstance(target, Array):
        _remove_array_items(target, drop)
    elif isinstance(target, str | String):
        items = parse_comma_delimited(target)
        kept = [item for item in items if item not in drop]
        if len(kept) < len(items):
            doc[key] = ",".join(kept)
    else:
        return
    if not doc[key]:
        del doc[key]


def remove_values(doc: Any, retired: Any) -> None:
    """
    Remove retired values from doc, in place.

    retired mirrors doc's structure. An array in it lists values to drop from
    the array, or from the comma-delimited string, at the same key path in doc.
    An array, string or table emptied that way is removed, so a fully retired
    key vanishes instead of lingering as `[]`, `""` or a bare `[tool.x]`. Any
    other value drops the key itself when doc holds that same value. Missing
    keys are ignored, the rest of each array keeps its order and formatting,
    and the rest of each string keeps its order.
    """
    for key, value in retired.items():
        if key not in doc:
            continue
        target = doc[key]
        if _is_table_like(value) and _is_table_like(target):
            remove_values(target, value)
            if not target:
                del doc[key]
        elif isinstance(value, list | Array):
            _remove_items(doc, key, frozenset(str(item) for item in value))
        elif value == target:
            del doc[key]


def load_toml_file(filepath: Path) -> TOMLDocument:
    """
    Load a TOML file and return its contents as a tomlkit document.

    Args:
        filepath: Path to the TOML file

    Returns:
        The parsed TOML content as a tomlkit document

    """
    content = filepath.read_text()
    return tomlkit.parse(content)


def _strip_toml_extra(dep_string: str) -> str:
    """
    Strip the 'toml' extra from a dependency string.

    Since Python 3.11 includes tomllib in the stdlib, packages no longer need
    the [toml] extra for TOML support.

    Examples:
        "radon[toml]>=5.1" -> "radon>=5.1"
        "foo[bar,toml]>=1.0" -> "foo[bar]>=1.0"
        "plain-package>=1.0" -> "plain-package>=1.0"

    """
    try:
        req = Requirement(dep_string.strip())
    except InvalidRequirement:
        return dep_string
    if TOML_EXTRA not in req.extras:
        return dep_string
    new_extras = sorted(req.extras - {TOML_EXTRA})
    extras_str = f"[{','.join(new_extras)}]" if new_extras else ""
    spec_str = str(req.specifier) if req.specifier else ""
    marker_str = f" ; {req.marker}" if req.marker else ""
    url_str = f" @ {req.url}" if req.url else ""
    return f"{req.name}{extras_str}{spec_str}{url_str}{marker_str}"


def _strip_toml_extras_from_dep_list(
    container: dict[str, Any] | Table | InlineTable | TOMLDocument,
    key: str,
) -> None:
    """Strip [toml] extras from the dependency list at key, in place."""
    deps = container.get(key)
    if not isinstance(deps, list):
        return
    for index, dep in enumerate(deps):
        if (stripped := _strip_toml_extra(str(dep))) != str(dep):
            deps[index] = stripped


def _strip_toml_extras_if_needed(
    merged: TOMLDocument | Table | InlineTable | dict[str, Any],
) -> None:
    """
    Strip [toml] extras from all dependency lists when requires-python >= 3.11.

    Python 3.11 added tomllib to the stdlib, making the [toml] extra
    unnecessary for packages that used it only for TOML config support.
    """
    project: dict[str, Any] = merged.get("project", {})
    if not isinstance(project, dict | Table | InlineTable | TOMLDocument):
        return

    requires_python = project.get("requires-python")
    if not requires_python:
        return

    version = _parse_version_from_requires_python(str(requires_python))
    if not version or version < MIN_PYTHON_VERSION_FOR_BUILTIN_TOML:
        return

    # project.dependencies
    _strip_toml_extras_from_dep_list(project, "dependencies")

    # build-system.requires
    build_system = merged.get("build-system", {})
    if isinstance(build_system, dict | Table | InlineTable | TOMLDocument):
        _strip_toml_extras_from_dep_list(build_system, "requires")

    # dependency-groups.*
    dep_groups = merged.get("dependency-groups", {})
    if isinstance(dep_groups, dict | Table | InlineTable | TOMLDocument):
        for group_name in dep_groups:
            _strip_toml_extras_from_dep_list(dep_groups, group_name)


def merge_toml_files(
    filepaths: Sequence[Path], list_strategy: str = "merge"
) -> TOMLDocument:
    """
    Merge TOML files into the last one, keeping its layout, and return it.

    Each earlier file fills in what the files after it lack, the latest first,
    so a later file's value wins where both hold one.

    Args:
        filepaths: TOML files, in increasing order of precedence
        list_strategy: How to handle lists - 'merge' (default) or 'replace'

    Returns:
        The last file's tomlkit document, merged

    """
    if not filepaths:
        return tomlkit.document()

    *bases, result = (load_toml_file(filepath) for filepath in filepaths)
    for base in reversed(bases):
        deep_merge_tomlkit(base, result, list_strategy)

    # Post-processing: strip [toml] extras if requires-python >= 3.11
    _strip_toml_extras_if_needed(result)

    return result


def main(argv: Sequence[str] | None = None) -> None:
    """
    Run CLI.

    Parses command-line arguments, validates input files, merges the files
    into the last one, and outputs the result to stdout or a file.
    """
    parser = argparse.ArgumentParser(
        description="Deep merge TOML files into the last one, keeping its layout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge a template into a project's file, output to stdout
  %(prog)s template.toml pyproject.toml

  # Merge and save to output file
  %(prog)s template.toml pyproject.toml -o pyproject.toml

  # Keep the project's arrays as they are
  %(prog)s template.toml pyproject.toml --list-strategy replace

Layout:
  The last file is the base. Its values, key order, comments and formatting
  stay, and each earlier file only adds the keys it lacks, each beside its
  neighbours in the earlier file. Where both files hold a value, the later
  file's wins, except:

Arrays:
  merge (default) keeps the later file's items in order and appends the
  earlier file's items it lacks. replace keeps the later file's array.
  An array of tables is always the later file's.

    template.toml:  addopts = ["--cov", "-ra"]
    pyproject.toml: addopts = ["-ra", "--strict-markers"]
    result:         addopts = ["-ra", "--strict-markers", "--cov"]

Python Dependency Merging:
  Lists at these TOML paths always merge by package, whatever the list
  strategy. The higher version wins in place; a missing package is appended:
    - project.dependencies
    - dependency-groups.* (any dependency group)
    - build-system.requires

    template.toml:  dependencies = ["requests>=2.31.0", "rich>=13.0.0"]
    pyproject.toml: dependencies = ["click>=8.0.0", "requests>=2.28.0"]
    result:         dependencies = ["click>=8.0.0", "requests>=2.31.0", "rich>=13.0.0"]

  Once requires-python is 3.11 or more, dependencies lose their [toml] extra.

Python Versions:
  requires-python, tool.ruff.target-version, tool.basedpyright.pythonVersion
  and tool.ty.environment.python-version keep the higher version.

Comma-Delimited Strings:
  tool.codespell.builtin, ignore-words-list and skip, and tool.radon.exclude
  are comma-delimited lists. They merge like arrays. Other strings, commas
  or not, are plain values.

    template.toml:  skip = "dist,uv.lock"
    pyproject.toml: skip = "uv.lock,mine"
    result:         skip = "uv.lock,mine,dist"
        """,
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="TOML files to merge, in increasing precedence; the last is the base",
    )

    parser.add_argument(
        "-o", "--output", type=Path, help="Output file path (default: stdout)"
    )

    parser.add_argument(
        "--list-strategy",
        choices=LIST_STRATEGIES,
        default="merge",
        help=(
            "How to merge an array or comma list both files hold: merge"
            " (default) appends the earlier file's missing items to the later"
            " file's; replace keeps the later file's. Dependency lists always"
            " merge."
        ),
    )

    parser.add_argument(
        "--remove-values",
        type=Path,
        help="TOML file of retired values to drop from the merged result",
    )

    args = parser.parse_args(argv)

    # Validate input files exist
    for filepath in [
        *args.files,
        *([args.remove_values] if args.remove_values else []),
    ]:
        if not filepath.exists():
            reason = f"File not found: {filepath}"
            parser.error(reason)

    merged_doc = merge_toml_files(args.files, args.list_strategy)
    if args.remove_values:
        remove_values(merged_doc, load_toml_file(args.remove_values))

    toml_output = tomlkit.dumps(merged_doc)
    if args.output:
        args.output.write_text(toml_output)
        print(f"Merged TOML written to: {args.output}")  # noqa: T201
    else:
        print(toml_output)  # noqa: T201


if __name__ == "__main__":
    main()
