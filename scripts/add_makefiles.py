#!/usr/bin/env python3
"""Add feature makefiles (and associated files) to a project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from _devenv_common import (  # pyright: ignore[reportImplicitRelativeImport]
    ALL_FEATURES,
    format_makefiles,
    get_devenv_src,
    report_counts,
)
from copy_files import copy_files  # pyright: ignore[reportImplicitRelativeImport]

DEFAULT_FEATURES = ("common", "node", "python")


def main() -> None:
    """CLI entry point for add_makefiles."""
    parser = argparse.ArgumentParser(description="Add feature makefiles to a project")
    parser.add_argument(
        "features",
        nargs="*",
        default=list(DEFAULT_FEATURES),
        help=(
            f"Features to add (default: {', '.join(DEFAULT_FEATURES)}). "
            f"Available: {', '.join(ALL_FEATURES)}"
        ),
    )
    args = parser.parse_args()

    features: list[str] = args.features
    devenv_src = get_devenv_src()
    pd = Path.cwd()

    # Set DEVENV_ env vars so copy_files picks up the features
    for feature in features:
        os.environ[f"DEVENV_{feature.upper()}"] = "1"

    print(f"Adding features: {' '.join(features)}")  # noqa: T201

    # Copy root files for these features
    copied, skipped, _paths = copy_files(devenv_src / "copy", pd, features)
    report_counts("Copied files", copied=copied, skipped=skipped)

    # Format makefiles
    if mk_files := sorted(pd.glob("cfg/*.mk")):
        format_makefiles([pd / "Makefile", *mk_files])


if __name__ == "__main__":
    main()
