"""Edit and format a project's Makefile and cfg/*.mk."""  # noqa: INP001

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

from _devenv_common import FEATURES

if TYPE_CHECKING:
    from collections.abc import Collection

# help.mk ships with common and must come last: it reads every makefile
# included before it.
INCLUDE_ORDER: Final = (*FEATURES, "help")
_INCLUDE_RE = re.compile(r"^(?P<comment>#\s*)?include\s+cfg/(?P<name>\w+)\.mk\s*$")


def _find_includes(lines: list[str]) -> dict[str, tuple[int, bool]]:
    """Map each feature to (line index, commented) of its first include line."""
    found: dict[str, tuple[int, bool]] = {}
    for i, line in enumerate(lines):
        if (match := _INCLUDE_RE.prefixmatch(line)) and match["name"] in INCLUDE_ORDER:
            found.setdefault(match["name"], (i, bool(match["comment"])))
    return found


def included_features(makefile: Path) -> list[str]:
    """Return the features a Makefile includes, ignoring commented includes."""
    if not makefile.exists():
        return []
    found = _find_includes(makefile.read_text().splitlines())
    return [name for name in FEATURES if name in found and not found[name][1]]


def _insert_position(lines: list[str], name: str, found: dict[str, int]) -> int:
    """Return where an include for name belongs among the existing ones."""
    rank = INCLUDE_ORDER.index(name)
    if before := [found[n] for n in INCLUDE_ORDER[:rank] if n in found]:
        return max(before) + 1
    if after := [found[n] for n in INCLUDE_ORDER[rank + 1 :] if n in found]:
        return min(after)
    includes = [i for i, line in enumerate(lines) if line.startswith("include ")]
    return includes[-1] + 1 if includes else len(lines)


def include_features(text: str, features: Collection[str]) -> str:
    """
    Make a Makefile include cfg/<feature>.mk for each feature.

    A commented include is uncommented in place, and a missing one is inserted
    beside its neighbours in INCLUDE_ORDER. Nothing is removed or reordered,
    so running it again changes nothing.
    """
    wanted = {*features, "help"} if "common" in features else set(features)
    lines = text.splitlines()
    found = {name: i for name, (i, _commented) in _find_includes(lines).items()}
    for name in INCLUDE_ORDER:
        if name not in wanted:
            continue
        include = f"include cfg/{name}.mk"
        if name in found:
            lines[found[name]] = include
            continue
        pos = _insert_position(lines, name, found)
        lines.insert(pos, include)
        found = {n: i + 1 if i >= pos else i for n, i in found.items()}
        found[name] = pos
    return "\n".join(lines) + "\n"


def format_makefiles() -> None:
    """Format the project Makefile and cfg/*.mk with mbake."""
    from mbake import Config, MakefileFormatter

    files = []
    pd = Path.cwd()
    root_makefile = pd / "Makefile"
    if root_makefile.exists():
        files.append(root_makefile)
    files += sorted(pd.glob("cfg/*.mk"))
    if not files:
        return

    formatter = MakefileFormatter(Config.load_or_default())
    all_errors: list[str] = []
    for path in files:
        _changed, errors, _warnings = formatter.format_file(path)
        all_errors.extend(f"{path}: {e}" for e in errors)
    if all_errors:
        raise RuntimeError("mbake formatting failed:\n" + "\n".join(all_errors))
