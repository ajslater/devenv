"""copy_files installs feature files into a project."""

from typing import TYPE_CHECKING

import copy_files

if TYPE_CHECKING:
    from pathlib import Path


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
