"""copy_files installs feature files into a project."""

lazy from pathlib import Path

import copy_files


def test_copied_script_keeps_its_mode(tmp_path: Path) -> None:
    """A copied bin script stays executable; Path.copy needs preserve_metadata."""
    src = tmp_path / "copy" / "common" / "bin" / "tool.sh"
    src.parent.mkdir(parents=True)
    src.write_text("#!/bin/sh\n")
    mode = 0o755
    src.chmod(mode)
    dest = tmp_path / "project"
    dest.mkdir()

    copied, skipped, dest_files = copy_files.copy_files(
        tmp_path / "copy", dest, ["common"]
    )

    assert (copied, skipped) == (1, 0)
    assert dest_files == [dest / "bin" / "tool.sh"]
    assert (dest / "bin" / "tool.sh").stat().st_mode & 0o777 == mode


def _ship(root: Path, feature: str, rel: str) -> None:
    src = root / feature / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("devenv's\n")


def test_delete_disabled_files_deletes_only_devenvs_bytes(tmp_path: Path) -> None:
    """A file a disabled feature ships goes unless the project owns it."""
    root = tmp_path / "copy"
    for rel in ("bin/gone.sh", "bin/edited.sh", "bin/linked.sh", "bin/shared.sh"):
        _ship(root, "node", rel)
    _ship(root, "common", "bin/shared.sh")
    dest = tmp_path / "project"
    (dest / "bin").mkdir(parents=True)
    for rel in ("bin/gone.sh", "bin/shared.sh", "devenvs"):
        (dest / rel).write_text("devenv's\n")
    (dest / "bin" / "edited.sh").write_text("the project's\n")
    (dest / "bin" / "linked.sh").symlink_to(dest / "devenvs")

    copy_files.delete_disabled_files(root, dest, ["common"])

    assert sorted(path.name for path in (dest / "bin").iterdir()) == [
        "edited.sh",
        "linked.sh",
        "shared.sh",
    ]


def test_delete_disabled_files_removes_only_dirs_it_empties(tmp_path: Path) -> None:
    """The emptied action dirs go; the project's own workflows dir stays."""
    root = tmp_path / "copy"
    _ship(root, "ci", ".github/actions/devenv-x/action.yml")
    _ship(root, "ci", ".github/workflows/devenv-check.yml")
    dest = tmp_path / "project"
    copy_files.copy_files(root, dest, ["ci"])
    (dest / ".github" / "workflows" / "ci.yml").write_text("the project's\n")
    (dest / "empty").mkdir()

    copy_files.delete_disabled_files(root, dest, ["common"])

    assert sorted(str(path.relative_to(dest)) for path in dest.rglob("*")) == [
        ".github",
        ".github/workflows",
        ".github/workflows/ci.yml",
        "empty",
    ]
