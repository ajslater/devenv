#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "ruamel.yaml~=0.19.1",
# ]
# ///
"""
Deep merge YAML files, keeping the last file's comments, order and style.

The last file is the base of the result, so its values win and its comments,
tags, anchors, quoting and key order all survive. Each earlier file only adds
what the later ones lack: missing keys go at the end of their mapping, and
missing list items at the end of their list. A value the last file shares
through an alias or a `<<` merge key is never changed in place: what gets
added to it goes to a copy that its key then owns.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from functools import partial, reduce
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

# Wider than any line, so long scalars stay on one line, as prettier keeps them.
_WIDTH: Final = 4096
# Where in an entry's comment slots ruamel keeps the comment that follows it.
_MAP_POST_COMMENT: Final = 2
_SEQ_POST_COMMENT: Final = 0


def _yaml(indent: int = 2) -> YAML:
    """Return a round-trip YAML that writes lists indented under their key."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = _WIDTH
    yaml.indent(mapping=indent, sequence=indent + 2, offset=indent)
    return yaml


def _collections(node: Any, seen: set[int] | None = None) -> Generator[Any]:
    """
    Yield each collection in node, once for each way the document reaches it.

    An anchored collection is reached again through each alias of it, and an
    inherited value through each mapping whose `<<` merge key brings it in.
    Each collection is descended into once, which also ends recursive aliases.
    """
    if not isinstance(node, CommentedMap | CommentedSeq):
        return
    yield node
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    for child in node.values() if isinstance(node, CommentedMap) else node:
        yield from _collections(child, seen)


def _anchor(node: Any) -> Any:
    """Return a collection's anchor, or None if it has none."""
    if isinstance(node, CommentedMap | CommentedSeq):
        anchor = node.yaml_anchor()
        if anchor is not None and anchor.value:
            return anchor
    return None


def _keep_anchors(doc: CommentedMap) -> None:
    """Write back every anchor, not only the ones something aliases yet."""
    for node in _collections(doc):
        if (anchor := _anchor(node)) is not None:
            anchor.always_dump = True


def _shared(doc: CommentedMap) -> Mapping[int, Any]:
    """Return the collections doc reaches more than once, by id."""
    nodes = list(_collections(doc))
    counts = Counter(map(id, nodes))
    # Holding the nodes keeps their ids from being reused while in use.
    return {id(node): node for node in nodes if counts[id(node)] > 1}


def _last_entry(node: Any) -> tuple[Any, int] | None:
    """Return a block collection's last own key or index, and its slot."""
    match node:
        case CommentedMap() if not node.fa.flow_style():
            # Keys a `<<` merge key brings in belong to the anchored mapping.
            keys = [key for key, _ in node.non_merged_items()]
            return (keys[-1], _MAP_POST_COMMENT) if keys else None
        case CommentedSeq() if node and not node.fa.flow_style():
            return len(node) - 1, _SEQ_POST_COMMENT
        case _:
            return None


def _tail_slot(node: Any) -> tuple[Any, Any, int] | None:
    """
    Return the (collection, key, slot) of the comment that ends node.

    ruamel keeps the blank lines and comments that follow a block collection
    in the post comment of its deepest last entry.
    """
    if (last := _last_entry(node)) is None:
        return None
    key, slot = last
    # An anchored entry's own lines belong where its anchor is written.
    if _anchor(child := node[key]) is not None:
        return node, key, slot
    return _tail_slot(child) or (node, key, slot)


def _take_tail(node: Any) -> str:
    """Cut the lines that follow node from its last entry, and return them."""
    if (found := _tail_slot(node)) is None:
        return ""
    owner, key, slot = found
    token = owner.ca.items.get(key, [None] * 4)[slot]
    if token is None:
        return ""
    line, newline, tail = token.value.partition("\n")
    token.value = line + newline
    return tail


def _give_tail(node: Any, tail: str) -> None:
    """Put tail, as cut by _take_tail, after node's last entry."""
    if not tail or (found := _tail_slot(node)) is None:
        return
    owner, key, slot = found
    comments = owner.ca.items.setdefault(key, [None] * 4)
    if comments[slot] is None:
        comments[slot] = CommentToken("\n", CommentMark(0))
    comments[slot].value += tail


@contextmanager
def _keeping_tail(node: Any) -> Generator[None]:
    """Keep the blank lines and comments after node there while it changes."""
    tail = _take_tail(node)
    yield
    _give_tail(node, tail)


def _edit(
    mapping: CommentedMap,
    key: Any,
    edit: Callable[[Any], None],
    shared: Mapping[int, Any],
) -> None:
    """
    Apply edit to mapping[key] without changing what other keys share.

    A value inherited through a `<<` merge key, or reached through an alias,
    is shared, so edit gets a deep copy without anchors instead. The copy
    becomes the key's own value only if edit changed it, so a shared value
    the edit leaves alone keeps its alias or merge key.
    """
    target = mapping[key]
    own = any(own_key == key for own_key, _ in mapping.non_merged_items())
    if own and id(target) not in shared:
        edit(target)
        return
    copy = deepcopy(target)
    for node in _collections(copy):
        node.yaml_set_anchor(None)
    _take_tail(copy)
    edit(copy)
    if copy != target:
        mapping[key] = copy


def _name(item: Any) -> Any:
    """
    Return what a list item is matched by.

    A one-key mapping is matched by its key: mkdocs names a plugin either
    `minify` or `minify: {...}`, and both are the same plugin.
    """
    if isinstance(item, CommentedMap) and len(item) == 1:
        return next(iter(item))
    return item


def _merge_lists(base: CommentedSeq, update: CommentedSeq) -> None:
    """Append base's items that update lacks to update, each once."""
    names = [_name(item) for item in update]
    with _keeping_tail(update):
        for item in base:
            if (name := _name(item)) not in names:
                names.append(name)
                _take_tail(item)
                update.append(item)


def _merge_value(
    value: Any, target: Any, list_strategy: str, shared: Mapping[int, Any]
) -> None:
    """Merge one key's base value into update's target, in place."""
    match value, target:
        case CommentedMap(), CommentedMap():
            deep_merge(value, target, list_strategy, shared)
        case CommentedSeq(), CommentedSeq() if list_strategy == "merge":
            _merge_lists(value, target)
        case _:
            pass


def deep_merge(
    base: CommentedMap,
    update: CommentedMap,
    list_strategy: str = "merge",
    shared: Mapping[int, Any] | None = None,
) -> CommentedMap:
    """
    Merge base into update, in place, and return update.

    update's values win. base adds the keys update lacks, at the end of their
    mapping, and, with the merge list strategy, the list items update lacks,
    at the end of their list. With the replace strategy update's lists stand.
    A value update shares through an alias or a `<<` merge key is never
    changed: what base adds to it goes to a copy owned by its key.
    """
    shared = _shared(update) if shared is None else shared
    with _keeping_tail(update):
        for key, value in base.items():
            if key not in update:
                _take_tail(value)
                update[key] = value
                continue
            merge = partial(
                _merge_value, value, list_strategy=list_strategy, shared=shared
            )
            _edit(update, key, merge, shared)
    return update


def _remove_items(target: CommentedSeq, drop: CommentedSeq) -> None:
    """Remove the items drop lists from target; a bare name drops by name."""
    with _keeping_tail(target):
        for index in reversed(range(len(target))):
            item = target[index]
            if item in drop or _name(item) in drop:
                del target[index]


def _retire(retired: Any, target: Any, shared: Mapping[int, Any]) -> None:
    """Remove one key's retired values from data's target, in place."""
    match retired, target:
        case CommentedMap(), CommentedMap():
            remove_values(target, retired, shared)
        case CommentedSeq(), CommentedSeq():
            _remove_items(target, retired)
        case _:
            pass


def remove_values(
    data: CommentedMap,
    retired: CommentedMap,
    shared: Mapping[int, Any] | None = None,
) -> None:
    """
    Remove retired values from data, in place.

    retired mirrors data's structure. A list in it names values to drop from
    the list at the same key path in data. A bare name also drops a one-key
    mapping by that name, so `minify` retires `minify: {...}` too; any other
    value drops only an equal item. A mapping or list emptied by retirement
    is removed, so a fully retired key vanishes instead of lingering as `{}`
    or `[]`. Missing keys are ignored and everything else keeps its order.
    Like a merge, retirement never changes a value data shares through an
    alias or a `<<` merge key; the key gets its own copy instead.
    """
    shared = _shared(data) if shared is None else shared
    with _keeping_tail(data):
        for key, value in retired.items():
            if key not in data:
                continue
            _edit(data, key, partial(_retire, value, shared=shared), shared)
            target = data[key]
            if isinstance(target, CommentedMap | CommentedSeq) and not target:
                del data[key]


def load_yaml_text(text: str, source: object = "YAML text") -> CommentedMap:
    """Load a YAML mapping for round-tripping; empty text is an empty one."""
    content = _yaml().load(text)
    if content is None:
        return CommentedMap()
    if not isinstance(content, CommentedMap):
        reason = f"{source} does not contain a YAML mapping at its root"
        raise TypeError(reason)
    _keep_anchors(content)
    return content


def load_yaml_file(filepath: Path) -> CommentedMap:
    """Load a YAML file's mapping for round-tripping."""
    return load_yaml_text(filepath.read_text(), filepath)


def dump_yaml(data: CommentedMap, indent: int = 2) -> str:
    """Write data as YAML text, as it was loaded where unchanged."""
    stream = StringIO()
    _yaml(indent).dump(data, stream)
    return stream.getvalue()


def merge_yaml_files(
    filepaths: Sequence[Path], list_strategy: str = "merge"
) -> CommentedMap:
    """
    Merge YAML files in order; later files win and keep their layout.

    An empty file merges like a missing one, so a template merged into an
    empty file keeps the template's own layout.
    """
    docs = [doc for path in filepaths if (doc := load_yaml_file(path))]
    merge = partial(deep_merge, list_strategy=list_strategy)
    return reduce(merge, docs, CommentedMap())


def main(argv: Sequence[str] | None = None) -> None:
    """
    Run CLI.

    Parses command-line arguments, validates input files, performs the merge,
    and outputs the result to stdout or a file.
    """
    parser = argparse.ArgumentParser(
        description="Deep merge multiple YAML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge three files, output to stdout
  %(prog)s base.yaml overrides.yaml local.yaml

  # Merge and save to output file
  %(prog)s base.yaml overrides.yaml -o merged.yaml

  # Let the last file's lists replace earlier ones instead of merging
  %(prog)s base.yaml overrides.yaml --list-strategy replace

The last file is the base of the result: its values, comments, tags, anchors,
quoting and key order win. Earlier files add the keys it lacks, at the end of
their mapping. Lists merge by value: the last file's items in its order, then
earlier files' items it lacks. A one-key mapping item matches a bare item of
the same name, so mkdocs' `minify` and `minify: {...}` are one plugin.
A value shared through an alias or a `<<` merge key is never changed; what
gets added to it goes to a copy that its key then owns.

--remove-values takes a YAML file that mirrors the merged one. A list in it
names values to drop from the list at the same key path, and a list or
mapping emptied that way is removed.
        """,
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="YAML files to merge (in order of precedence - later files override earlier ones)",
    )

    parser.add_argument(
        "-o", "--output", type=Path, help="Output file path (default: stdout)"
    )

    parser.add_argument(
        "--list-strategy",
        choices=["merge", "replace"],
        default="merge",
        help="How to handle list merging: merge (default) or replace",
    )

    parser.add_argument(
        "--remove-values",
        type=Path,
        help="YAML file of retired values to drop from the merged result",
    )

    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces for YAML indentation (default: 2)",
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

    merged_data = merge_yaml_files(args.files, args.list_strategy)
    if args.remove_values:
        remove_values(merged_data, load_yaml_file(args.remove_values))

    yaml_output = dump_yaml(merged_data, args.indent)
    if args.output:
        args.output.write_text(yaml_output)
        print(f"Merged YAML written to: {args.output}")  # noqa: T201
    else:
        print(yaml_output, end="")  # noqa: T201


if __name__ == "__main__":
    main()
