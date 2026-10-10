#!/usr/bin/env python3
# /// script
# requires-python = ">=3.15"
# dependencies = [
#   "semver~=3.1",
# ]
# ///
"""
Deep merge package.json files, each into the result of those before it.

Scalars from later files win, objects merge recursively, arrays are a union,
script `&&` chains are an ordered union of commands, and dependency specs keep
the higher version constraint. `main --help` details the policy.
"""

import argparse
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import semver
from _devenv_common import read_lines  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

SCRIPT_COMMAND_SEPARATOR = " && "
NO_VERSION_SPECS = frozenset({"*", "latest", "", "next"})
WILDCARDS = frozenset({"x", "X", "*"})
UPPER_BOUND_OPERATORS: Final = frozenset({"<", "<="})
# A single npm comparator: an optional range operator followed by a partial
# semver. Matching the parts explicitly keeps operator and wildcard handling
# off the prerelease and build identifiers, which are free-form text.
COMPARATOR_RE = re.compile(
    r"""
    (?P<operator>\^|~>?|>=|<=|>|<|=)?\s*  # optional npm range operator
    v?                                    # optional leading v
    (?P<major>\d+|[xX*])
    (?:\.(?P<minor>\d+|[xX*]))?
    (?:\.(?P<patch>\d+|[xX*]))?
    (?:-(?P<prerelease>[0-9A-Za-z][0-9A-Za-z.-]*))?
    (?:\+(?P<build>[0-9A-Za-z][0-9A-Za-z.-]*))?
    """,
    re.VERBOSE,
)
# A protocol (workspace:, catalog:, npm:, link:, portal:, git+ssh:, https:,
# ...), or a path or GitHub owner/repo. npm semver ranges have neither a
# colon nor a slash, so anything matching names a source, not a range.
OPAQUE_SPEC_RE: Final = re.compile(r"^[A-Za-z][\w+.-]*:|/")
EPILOG: Final = """
Merge policy (each file merges into the result of the files before it):
  Scalars       the later file's value wins.
  Objects       merge key by key, recursively.
  Arrays        an array both files have becomes a de-duplicated union,
                sorted with plain strings before [name, options] pairs. An
                "overrides" array keeps its order, since prettier applies
                overrides in order: the earlier file's entries first, winning
                for the same "files" globs, then the later file's new ones.
                --list-strategy replace keeps the later file's array instead.
  Scripts       a script both files have is an ordered union of its "&&"
                commands: the later file's commands in its order, then the
                earlier file's commands it lacks.
  Dependencies  in every *dependencies object, the spec with the higher
                floor (the lowest version it admits) wins, whichever file it
                comes from (earlier + later -> merged):
                  ^4.17.1   + ^4.18.0  -> ^4.18.0
                  ^1.2.0    + 1.0.0    -> ^1.2.0    a lower project pin loses
                  ^1.2.0    + 1.5.0    -> 1.5.0     a higher one wins
                A bare >= or > beats any bounded range, even a higher one:
                  >=73.0.0  + ^73.1.0  -> >=73.0.0
                At an equal floor the wider range wins (^ over ~ over an
                exact pin), so an exact pin becomes a caret:
                  ^1.2.3    + 1.2.3    -> ^1.2.3
                An OR range ranks by its highest branch. A spec with no
                floor (*, latest, <2.0.0) loses to one with a floor; between
                two, the later file's wins. A protocol or path spec
                (workspace:, catalog:, npm:, link:, portal:, file:, git or
                http URLs, owner/repo) is kept as written and never
                compared; between two, the later file's wins.

Retirement, applied to the merged result:
  --remove FILE         drops each package it lists (one per line; blank and
                        # lines skipped) from every dependency section.
  --remove-values FILE  drops the array values and script commands it lists
                        at the same key path.
  An object or array that either option empties is dropped too.

Examples:
  # Merge the template into a project, as update-devenv does
  %(prog)s template/package.json package.json -o package.json

  # Merge, keeping the later file's arrays as they are
  %(prog)s package.json package-extra.json --list-strategy replace
"""


def _parse_script_commands(script_value: str) -> list[str]:
    """Split a script value into individual commands by '&&'."""
    return [
        cmd.strip()
        for cmd in script_value.split(SCRIPT_COMMAND_SEPARATOR)
        if cmd.strip()
    ]


def _remove_script_commands(script_value: str, retired: list[str]) -> str:
    """Drop retired commands from a script value's '&&' chain."""
    kept = [cmd for cmd in _parse_script_commands(script_value) if cmd not in retired]
    return SCRIPT_COMMAND_SEPARATOR.join(kept)


def merge_script_entry(base_value: str, update_value: str) -> str:
    """
    Merge two script entries as an ordered union of their '&&' commands.

    The later (update) chain keeps its order, repeats included, so a project
    can put its own step before or between the template's. The base commands
    it lacks follow, in base order.
    """
    update_commands = _parse_script_commands(update_value)
    missing = [
        cmd for cmd in _parse_script_commands(base_value) if cmd not in update_commands
    ]
    return SCRIPT_COMMAND_SEPARATOR.join([*update_commands, *missing])


def merge_scripts(base: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Merge two scripts objects, merging the scripts both have by command."""
    result = base.copy()
    for key, value in updates.items():
        result[key] = merge_script_entry(result[key], value) if key in result else value
    return result


def is_spec_opaque(spec: str) -> bool:
    """Determine if the spec names a source (protocol or path), not a range."""
    return OPAQUE_SPEC_RE.search(spec.strip()) is not None


def _comparator_version(match: re.Match[str]) -> str | None:
    """Build a full semver version from a matched npm comparator."""
    core = ".".join(
        "0" if part is None or part in WILDCARDS else part
        for part in (match["major"], match["minor"], match["patch"])
    )
    prerelease = f"-{match['prerelease']}" if match["prerelease"] else ""
    build = f"+{match['build']}" if match["build"] else ""
    version = core + prerelease + build

    # Validate it's a proper version
    try:
        semver.VersionInfo.parse(version)
    except ValueError, AttributeError:
        return None
    return version


def _extract_branch_version(branch: str) -> str | None:
    """Extract the floor version of a single non-OR range branch."""
    # The leftmost lower bound is the floor for both compound ranges
    # (">=9.0.0 <9.5.0") and hyphen ranges ("1.2.3 - 2.3.4"). An upper
    # bound is no floor, so "<2.0.0" alone has none.
    for match in COMPARATOR_RE.finditer(branch):
        if match["operator"] not in UPPER_BOUND_OPERATORS:
            return _comparator_version(match)
    return None


def extract_version_from_range(version_str: str) -> str | None:
    """Extract a base semver version from an npm version range string."""
    # Handle special cases
    if version_str.strip() in NO_VERSION_SPECS:
        return None

    # An OR range admits everything its widest branch admits, so rank it by
    # the highest branch floor rather than by the first branch listed.
    versions = [
        version
        for branch in version_str.split("||")
        if (version := _extract_branch_version(branch)) is not None
    ]
    return max(versions, key=semver.VersionInfo.parse) if versions else None


def get_version_prefix(version_str: str) -> str:
    """Extract the npm range prefix from a version string."""
    # Order matters: >= and <= must come before > and
    if match := re.prefixmatch(r"^([\^~]|>=|<=|>|<|=)", version_str):
        return match.group(1)
    return "="


def is_spec_unbounded(spec_str: str) -> bool:
    """Determine if the spec is a bare > or >= range with no upper bound."""
    return re.fullmatch(r">=?\s*v?\d[\w.\-+]*", spec_str.strip()) is not None


def _merge_extracted_dep_ranges(
    base_spec, update_spec, base_extracted: str, update_extracted: str
):
    """Compare the extracted versions, preferring the range allowing higher versions."""
    try:
        base_ver = semver.VersionInfo.parse(base_extracted)
        update_ver = semver.VersionInfo.parse(update_extracted)

        # An unbounded range (> or >=) admits every version a bounded range
        # does and more, so it wins regardless of the extracted floors.
        base_unbounded = is_spec_unbounded(base_spec)
        update_unbounded = is_spec_unbounded(update_spec)
        if base_unbounded != update_unbounded:
            return base_spec if base_unbounded else update_spec

        # Compare versions
        if update_ver > base_ver:
            return update_spec
        if base_ver > update_ver:
            return base_spec
        # Versions are equal, prefer more flexible range.
        # Priority: ^ > ~ > >= > > > exact. A > or >= reaching here is always
        # part of a bounded compound like ">=9.0.0 <9.5.0" (bare ones were
        # settled above), so it must not outrank ^ or ~; ranking >= over >
        # only decides the both-unbounded tie.
        base_prefix = get_version_prefix(base_spec)
        update_prefix = get_version_prefix(update_spec)

        prefix_priority = {"": 0, "=": 0, ">": 1, ">=": 2, "~": 3, "^": 4}
        base_priority = prefix_priority.get(base_prefix, 0)
        update_priority = prefix_priority.get(update_prefix, 0)

        result_spec = update_spec if update_priority > base_priority else base_spec

    except ValueError, AttributeError:
        # If comparison fails, prefer update
        result_spec = update_spec
    return result_spec


def merge_dependency_specs(base_spec: str, update_spec: str) -> str:
    """
    Merge two npm semver version strings, preferring the higher version.

    Uses the semver package for proper semantic version comparison.
    Handles npm-specific version ranges (^, ~, >=, etc.). An opaque spec is
    kept as written; between two, the update wins.
    """
    if is_spec_opaque(update_spec):
        return update_spec
    if is_spec_opaque(base_spec):
        return base_spec

    # Try to extract actual versions from ranges
    base_extracted = extract_version_from_range(base_spec)
    update_extracted = extract_version_from_range(update_spec)

    # If we can't parse either, prefer the update
    if base_extracted is None and update_extracted is None:
        return update_spec

    # If only one is parseable, use that one
    if base_extracted is None:
        return update_spec
    if update_extracted is None:
        return base_spec

    return _merge_extracted_dep_ranges(
        base_spec, update_spec, base_extracted, update_extracted
    )


def merge_dependencies(base: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Merge two dependency objects, keeping the higher spec for shared packages."""
    result = base.copy()
    for package, version in updates.items():
        result[package] = (
            merge_dependency_specs(result[package], version)
            if package in result
            else version
        )
    return result


def _is_dependency_key(key: str) -> bool:
    """Name dependencies, devDependencies, bundledDependencies and the like."""
    return key.lower().endswith("dependencies")


def _without_packages(section: Any, retired: frozenset[str]) -> Any:
    """Return a dependency object or array of names without the retired ones."""
    match section:
        case dict():
            return {name: spec for name, spec in section.items() if name not in retired}
        case list():
            return [name for name in section if name not in retired]
        case _:
            return section


def remove_packages(data: dict[str, Any], retired: frozenset[str]) -> None:
    """
    Drop retired packages from every dependency section, in place.

    An object section loses the package's key and an array section, such as
    bundledDependencies, its name. A section emptied this way is removed.
    """
    for key in [key for key in data if _is_dependency_key(key)]:
        section = data[key]
        kept = _without_packages(section, retired)
        if section and not kept:
            del data[key]
        else:
            data[key] = kept


def _json_key(item: Any) -> str:
    """Key an item by its JSON form, so unhashable items compare by value."""
    return json.dumps(item, sort_keys=True)


def _override_key(item: Any) -> str:
    """Key a prettier override by its files globs; other items by value."""
    if isinstance(item, dict) and "files" in item:
        files = item["files"]
        return _json_key(sorted(files) if isinstance(files, list) else [files])
    return _json_key(item)


def _list_item_sort_key(item: Any) -> tuple[int, str, str]:
    """
    Order heterogeneous list items deterministically.

    Config lists such as remarkConfig.plugins hold either a bare name or a
    [name, options] pair. Sorting bare names first keeps configured entries
    after the presets they override, which is what makes a
    ["lint-no-duplicate-headings", false] entry disable the rule.
    """
    if isinstance(item, str):
        return (0, item, "")
    if item and isinstance(item, list) and isinstance(item[0], str):
        return (1, item[0], _json_key(item[1:]))
    return (2, _json_key(item), "")


def _dedupe_list(items: list[Any], key: Callable[[Any], str] = _json_key) -> list[Any]:
    """Drop items whose key an earlier item has; the rest keep their order."""
    deduped: dict[str, Any] = {}
    for item in items:
        deduped.setdefault(key(item), item)
    return list(deduped.values())


def _merge_lists(key: str, base: list[Any], update: list[Any]) -> list[Any]:
    """
    Union two arrays, sorted, except an "overrides" array keeps its order.

    Prettier applies overrides in order, so sorting them could change what
    they do. Base entries come first and win for the same files globs.
    """
    if key == "overrides":
        return _dedupe_list([*base, *update], _override_key)
    return sorted(_dedupe_list([*base, *update]), key=_list_item_sort_key)


def _merge_value(key: str, base: Any, update: Any, list_strategy: str) -> Any:
    """Merge one key's values; the update wins unless both are containers."""
    match base, update:
        case dict(), dict() if _is_dependency_key(key):
            return merge_dependencies(base, update)
        case dict(), dict() if key == "scripts":
            return merge_scripts(base, update)
        case dict(), dict():
            return deep_merge(base, update, list_strategy)
        case list(), list() if list_strategy == "merge":
            return _merge_lists(key, base, update)
        case _:
            return update


def deep_merge(
    base: dict[Any, Any], updates: dict[Any, Any], list_strategy: str = "merge"
) -> dict[Any, Any]:
    """Recursively merge updates into base; base keys keep their order."""
    result = base.copy()
    for key, value in updates.items():
        result[key] = (
            _merge_value(key, result[key], value, list_strategy)
            if key in result
            else value
        )
    return result


def load_package_json(filepath: Path) -> dict[Any, Any]:
    """Load a package.json file; an empty one, as `touch` leaves it, is {}."""
    text = filepath.read_text()
    content = json.loads(text) if text.strip() else {}
    if not isinstance(content, dict):
        reason = f"{filepath} does not contain a JSON object at root level"
        raise TypeError(reason)
    return content


def merge_package_json_files(
    filepaths: Sequence[Path], list_strategy: str = "merge"
) -> dict[Any, Any]:
    """Merge package.json files in order, each into the result of those before."""
    result: dict[Any, Any] = {}
    for filepath in filepaths:
        result = deep_merge(result, load_package_json(filepath), list_strategy)
    return result


def remove_values(data: Any, retired: Any) -> None:
    """
    Remove retired values from data, in place.

    retired mirrors data's structure. A list under an array key names values
    to drop from that array; a list under a script key names commands to drop
    from its `&&` chain. A value matches only when it is equal as a whole, so
    an object is dropped only if every field matches. A dict or array emptied
    by retirement is removed, so a fully retired config key vanishes instead
    of lingering as `{}` or `[]`. Missing keys are ignored and everything else
    keeps its order.
    """
    for key, value in retired.items():
        target = data.get(key) if isinstance(data, dict) else None
        match value, target:
            case dict(), dict():
                remove_values(target, value)
            case list(), list():
                target[:] = [item for item in target if item not in value]
            case list(), str():
                data[key] = _remove_script_commands(target, value)
                continue
            case _:
                continue
        if not target:
            del data[key]


def main(argv: Sequence[str] | None = None) -> None:
    """
    Run cli.

    Parses command-line arguments, validates input files, performs the merge
    with semver-aware dependency handling, and outputs the result to stdout or a file.
    """
    parser = argparse.ArgumentParser(
        description="Deep merge package.json files with semver-aware dependency merging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="package.json files to merge, earliest first (template, then project); an empty file counts as {}",
    )

    parser.add_argument(
        "-o", "--output", type=Path, help="Output file path (default: stdout)"
    )

    parser.add_argument(
        "--list-strategy",
        choices=["merge", "replace"],
        default="merge",
        help="How to merge arrays both files have: merge (default) takes their union, replace keeps the later file's array",
    )

    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces for JSON indentation (default: 2)",
    )

    parser.add_argument(
        "--remove",
        type=Path,
        help="File listing packages to drop from every dependency section",
    )

    parser.add_argument(
        "--remove-values",
        type=Path,
        action="append",
        default=[],
        help="JSON file of retired array values and script commands to drop from the merged result; may repeat",
    )

    args = parser.parse_args(argv)

    # Validate input files exist
    for filepath in [
        *args.files,
        *args.remove_values,
    ]:
        if not filepath.exists():
            reason = f"File not found: {filepath}"
            parser.error(reason)

    # Perform the merge, then retire what devenv no longer ships
    merged_data = merge_package_json_files(args.files, args.list_strategy)
    if args.remove:
        remove_packages(merged_data, frozenset(read_lines(args.remove)))
    for path in args.remove_values:
        remove_values(merged_data, load_package_json(path))

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
