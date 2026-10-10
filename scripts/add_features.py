#!/usr/bin/env python3
# /// script
# requires-python = ">=3.15"
# dependencies = [
#   "mbake~=1.4.5",
# ]
# ///
"""
Add devenv features to a project, or set up a new or old project.

Copies each feature's files from copy/<feature>/ and makes the project
Makefile include cfg/<feature>.mk in the canonical order. With --init it first
installs the starter files from init/<feature>/ without replacing any file the
project already has. --convert also keeps an old Makefile and
eslint.config.js as *.orig.* references before the starters take their place.
"""

import argparse
from pathlib import Path

from _devenv_common import (  # ty: ignore[unresolved-import]
    DEFAULT_FEATURES,
    FEATURES,
    exit_on_unmet_requirements,
    get_devenv_src,
    report_counts,
)
from _makefiles import (  # ty: ignore[unresolved-import]
    format_makefiles,
    include_features,
    included_features,
)
from copy_files import copy_files  # ty: ignore[unresolved-import]

# Old files convert keeps for reference, and the names it keeps them under.
CONVERT_RENAMES = (
    ("Makefile", "Makefile.orig.mk"),
    ("eslint.config.js", "eslint.config.orig.js"),
)


def resolve_features(requested: list[str], *, init: bool) -> list[str]:
    """
    Return the features the project ends up with, in canonical order.

    That is what the Makefile already includes plus the requested features,
    or the defaults when none are requested. A new project always gets the
    defaults.
    """
    current = [] if init else included_features(Path("Makefile"))
    defaults = DEFAULT_FEATURES if init or not requested else ()
    wanted = {*current, *defaults, *requested}
    exit_on_unmet_requirements(wanted)
    return [name for name in FEATURES if name in wanted]


def _keep_old_files() -> None:
    for name, orig_name in CONVERT_RENAMES:
        old, orig = Path(name), Path(orig_name)
        if old.is_file() and not orig.exists():
            old.rename(orig)
            print(f"Kept old {name} as {orig_name}")  # noqa: T201


def add_features(requested: list[str], *, init: bool, convert: bool) -> list[str]:
    """Add the features to the project in the current directory."""
    features = resolve_features(requested, init=init or convert)
    devenv_src = get_devenv_src()
    pd = Path.cwd()
    print(f"Features: {' '.join(features)}")  # noqa: T201

    if convert:
        _keep_old_files()
    if init or convert:
        copied, skipped, _paths = copy_files(
            devenv_src / "init", pd, features, clobber=False
        )
        report_counts("Starter files", copied=copied, kept=skipped)

    copied, skipped, _paths = copy_files(devenv_src / "copy", pd, features)
    report_counts("Copied files", copied=copied, skipped=skipped)

    makefile = pd / "Makefile"
    if makefile.exists():
        makefile.write_text(include_features(makefile.read_text(), features))
    else:
        print("No Makefile; add the cfg/*.mk includes yourself.")  # noqa: T201
    format_makefiles()
    return features


def main() -> None:
    """CLI entry point for add_features."""
    parser = argparse.ArgumentParser(
        description="Add devenv features to the project in the current directory"
    )
    parser.add_argument(
        "features",
        nargs="*",
        help=(
            f"Features to add (default: {' '.join(DEFAULT_FEATURES)}). "
            f"Available: {' '.join(FEATURES)}"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--init",
        action="store_true",
        help="Also install starter files from init/, keeping existing files",
    )
    mode.add_argument(
        "--convert",
        action="store_true",
        help=(
            "Like --init, but first keep an old Makefile and eslint.config.js"
            " as *.orig.* files"
        ),
    )
    args = parser.parse_args()
    add_features(args.features, init=args.init, convert=args.convert)


if __name__ == "__main__":
    main()
