#!/usr/bin/env python3
"""
Normalize NEWS.md sections to Keep a Changelog names under gitmoji headings.

Each version's legacy `- Features` style list labels become `### ✨ Added`
style headings in a fixed order, with their items dedented to the left margin.
Legacy labels that map to the same section merge in their original order.
Already converted files pass through unchanged, so the script is idempotent.

Usage: news_normalize.py NEWS.md
"""

import re
import sys
from pathlib import Path
from typing import Final

# Standard sections in output order: (name, gitmoji).
SECTIONS: Final = (
    ("Breaking Changes", "💥"),
    ("Added", "✨"),
    ("Changed", "♻️"),
    ("Deprecated", "🗑️"),
    ("Removed", "🔥"),
    ("Fixed", "🐛"),
    ("Security", "🔒"),
    ("Developer", "🧑‍💻"),
)
SECTION_NAMES: Final = frozenset(name for name, _ in SECTIONS)

# Legacy list labels, trailing colon stripped, to standard sections.
LEGACY: Final = {
    "Added": "Added",
    "Breaking Changes": "Breaking Changes",
    "Breaking Change": "Breaking Changes",
    "🚨 Big Changes 🚨": "Breaking Changes",
    "🚨 Breaking Changes": "Breaking Changes",
    "🚨 BREAKING CHANGES 🚨": "Breaking Changes",
    "Changed": "Changed",
    "**Warning**": "Breaking Changes",
    "Notice": "Breaking Changes",
    "Upgrading": "Breaking Changes",
    "Database Migration": "Breaking Changes",
    "Binary Dependencies": "Breaking Changes",
    "Features": "Added",
    "Feature": "Added",
    "Documentation": "Added",
    "Performance": "Changed",
    "Performance Improvements": "Changed",
    "Change": "Changed",
    "License": "Changed",
    "Removed": "Removed",
    "Drop Support": "Removed",
    "Fixes": "Fixed",
    "Fix": "Fixed",
    "Fixed": "Fixed",
    "Special Thanks": "Fixed",
    "Dependencies": "Developer",
    "Depends": "Developer",
    "Deps": "Developer",
    "Dev": "Developer",
    "Dev Notes": "Developer",
    "Development": "Developer",
    "Developer": "Developer",
    "Config": "Changed",
    "Security": "Security",
}

# Items listed outside any section in early versions.
UNSECTIONED: Final = {
    "Don't support Python 3.14 until dependencies do.": "Changed",
    "Docker image is now based on trixie debian": "Changed",
    "Dark admin pages and fix template overrides.": "Changed",
    "Automate multi-arch builds": "Developer",
    "Build Docker images for amd64 & arm64 manually.": "Developer",
    "Fix reader bug that only displayed first page": "Fixed",
    "Add LOGLEVEL environment variable.": "Added",
    "Removed DEV environment variable.": "Removed",
    "Possible fix for newly imported covers not displaying.": "Fixed",
    "Minor bugfixes.": "Fixed",
    "Productionized alpha release": "Added",
    "Polished VueJS frontend": "Added",
    "Single Page VueJS frontend PoC without much styling": "Added",
    "Working application with all initial features": "Added",
    "Django frontend": "Added",
    "Proof of concept.": "Added",
}

# Notes that are a version's only content become its heading subtitle.
STATUS: Final = {
    "Bad release. Does not start.": "Bad release, does not start",
    "Yanked. Broken Reader.": "Yanked, broken reader",
    "Yanked. Bad network behavior. Broken javascript.": (
        "Yanked, bad network behavior and broken javascript"
    ),
    "Yanked. Crash loading admin page.": "Yanked, crash loading admin page",
    "Broken docker container": "Broken docker container",
    "Upload mistake with 0.5.7. This is just a version bump.": (
        "Version bump for the 0.5.7 upload mistake"
    ),
}

HEADER_FIXES: Final = {"## v1.9.17 Broken build": "## v1.9.17 - Broken build"}

LEGACY_INDENT: Final = 4
HEADING_RE: Final = re.compile(r"^### (?:\S+ )?(?P<name>.+?)\s*$")
SUBGROUP_RE: Final = re.compile(r"^(?P<indent> *)- (?P<label>.+):$")


class NewsError(ValueError):
    """NEWS.md holds something the converter has no rule for."""


def _heading_name(line: str) -> str:
    """Return the standard section name of an already converted heading."""
    match = HEADING_RE.match(line)
    if not match or match["name"] not in SECTION_NAMES:
        reason = f"unknown section heading: {line!r}"
        raise NewsError(reason)
    return match["name"]


def _drop_subgroup_colons(lines: list[str]) -> list[str]:
    """Drop the trailing colon of a bullet that heads nested bullets."""
    result = []
    for index, line in enumerate(lines):
        match = SUBGROUP_RE.match(line)
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if match and following.startswith(match["indent"] + "    - "):
            line = f"{match['indent']}- {match['label']}"
        result.append(line)
    return result


def convert_version(header: str, body: list[str]) -> list[str]:
    """Convert one version's header and body lines."""
    header = HEADER_FIXES.get(header, header)
    sections: dict[str, list[str]] = {name: [] for name, _ in SECTIONS}
    target: list[str] | None = None
    dedent = 0
    thanks = False
    for line in body:
        if not line.strip():
            continue
        if line.startswith("### "):
            target, dedent, thanks = sections[_heading_name(line)], 0, False
        elif line.startswith(" ") or (dedent == 0 and target is not None):
            if target is None:
                reason = f"{header}: line outside a section: {line!r}"
                raise NewsError(reason)
            line = line[dedent:]
            if thanks and line.startswith("- To "):
                line = "- Thanks to " + line.removeprefix("- To ")
            target.append(line)
        else:
            text = line.removeprefix("- ")
            if (name := LEGACY.get(text.removesuffix(":"))) is not None:
                target, dedent = sections[name], LEGACY_INDENT
                thanks = text == "Special Thanks"
            elif (subtitle := STATUS.get(text)) is not None:
                if " - " in header:
                    reason = f"{header}: already has a subtitle"
                    raise NewsError(reason)
                header, target = f"{header} - {subtitle}", None
            elif (name := UNSECTIONED.get(text)) is not None:
                target, dedent, thanks = sections[name], 0, False
                target.append(f"- {text}")
            else:
                reason = f"{header}: unknown label or item: {line!r}"
                raise NewsError(reason)

    out = [header, ""]
    for name, emoji in SECTIONS:
        if lines := sections[name]:
            out += [f"### {emoji} {name}", "", *_drop_subgroup_colons(lines), ""]
    return out


def convert(news: str) -> str:
    """Convert a whole NEWS.md text."""
    lines = news.rstrip("\n").split("\n")
    starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    if not starts:
        return news
    out = lines[: starts[0]]
    for start, end in zip(starts, [*starts[1:], len(lines)], strict=True):
        out += convert_version(lines[start], lines[start + 1 : end])
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> None:
    """Rewrite the NEWS.md given on the command line in place."""
    path = Path(sys.argv[1])
    path.write_text(convert(path.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
