#!/usr/bin/env python3
"""
Update a project by merging devenv templates and copying root files.

Main orchestrator that:
1. Deletes obsolete files listed in remove_files.txt
2. Merges dotfiles from templates/
3. Copies root files from root/<feature>/
4. Merges config files (package.json, YAML, TOML)
5. Runs formatters on merged files
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from _devenv_common import (  # pyright: ignore[reportImplicitRelativeImport]
    format_makefiles,
    get_devenv_src,
    get_enabled_features,
    git_status,
    report_counts,
    run,
)
from copy_files import copy_files  # pyright: ignore[reportImplicitRelativeImport]
from merge_dotfiles import (  # pyright: ignore[reportImplicitRelativeImport]
    merge_dotfiles,
)


def delete_files(devenv_src: Path) -> None:
    """Delete files listed in remove_files.txt."""
    delete_file = devenv_src / "remove_files.txt"
    if not delete_file.exists():
        return

    existing: list[Path] = []
    for raw_line in delete_file.read_text().splitlines():
        entry = raw_line.strip()
        if not entry or entry.startswith("#"):
            continue
        path = Path(entry)
        if path.is_file():
            existing.append(path)

    if existing:
        print(f"Deleting {len(existing)} files...")  # noqa: T201
        for f in existing:
            f.unlink()


def merge_template(
    devenv_src: Path,
    project_dir: Path,
    template_rel: str,
    output_name: str,
    script: str,
    extra_args: list[str] | None = None,
) -> str:
    """
    Merge a template config file into the project using a merge script.

    Returns the output filename for inclusion in fix_files.
    """
    template_f = devenv_src / template_rel
    output_f = project_dir / output_name
    output_f.parent.mkdir(parents=True, exist_ok=True)
    output_f.touch(exist_ok=True)
    cmd: list[str | Path] = [
        "uv",
        "run",
        devenv_src / "scripts" / script,
        template_f,
        output_f,
        "-o",
        output_f,
    ]
    if extra_args:
        cmd.extend(extra_args)
    run(cmd)
    return output_name


def main() -> None:
    """Run the full devenv update pipeline."""
    devenv_src = get_devenv_src()
    pd = Path.cwd()
    features = get_enabled_features()

    # Init
    delete_files(devenv_src)
    (pd / "bin").mkdir(parents=True, exist_ok=True)
    (pd / "cfg").mkdir(parents=True, exist_ok=True)

    # Dotfiles
    created, skipped, merged, _dotfile_paths = merge_dotfiles(
        devenv_src / "merge", pd, features
    )
    report_counts("Merged dotfiles", created=created, skipped=skipped, merged=merged)
    run(["bin/sort-ignore.sh"])

    # Copy root files
    copied, file_skipped, _root_paths = copy_files(devenv_src / "copy", pd, features)
    report_counts("Copied files", copied=copied, skipped=file_skipped)

    # Format copied files
    mk_files = sorted(pd.glob("cfg/*.mk"))
    format_makefiles([pd / "Makefile", *mk_files])
    sh_files = sorted(pd.glob("bin/*.sh"))
    if sh_files:
        run(["shellharden", "--replace", *sh_files])

    # Merge config templates
    fix_files: list[str] = []

    if os.environ.get("DEVENV_NODE_ROOT"):
        fix_files.append(
            merge_template(
                devenv_src,
                pd,
                "merge/node_root/package.json",
                "package.json",
                "merge_package_json.py",
                ["--remove", str(devenv_src / "remove_node_packages.txt")],
            )
        )

    if os.environ.get("DEVENV_DOCS"):
        fix_files.extend(
            merge_template(devenv_src, pd, f"merge/docs/{name}", name, "merge_yaml.py")
            for name in (".readthedocs.yaml", "mkdocs.yml")
        )

    if os.environ.get("DEVENV_PYTHON"):
        fix_files.append(
            merge_template(
                devenv_src,
                pd,
                "merge/python/pyproject-template.toml",
                "pyproject.toml",
                "merge_toml.py",
            )
        )

    if os.environ.get("DEVENV_CI"):
        fix_files.extend(
            merge_template(devenv_src, pd, f"merge/ci/{name}", name, "merge_yaml.py")
            for name in ("compose.yaml",)
        )

    # Fix merged config files
    if fix_files:
        run(["bun", "update"])
        run(["bunx", "eslint", "--cache", "--fix", *fix_files])
        run(["bunx", "prettier", "--write", *fix_files])
        git_status([".*", "bin", "cfg", *fix_files])


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Update project with devenv templates and root files"
    ).parse_args()
    main()
