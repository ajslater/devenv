"""
copy/common/bin/sort-ignore.sh sorts each .*ignore file in place.

It drops duplicate lines and puts "!" negations after every other line. git,
docker and prettier let the last matching line win, so a negation only works
after the patterns it overrides. update_devenv runs it after copying bin/, so
a project's first update already sorts with the new script.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SORT_IGNORE = _ROOT / "copy" / "common" / "bin" / "sort-ignore.sh"
_BASH = shutil.which("bash") or ""
_GIT = shutil.which("git") or ""
# The sort-ignore.sh projects had before negations went last.
_OLD_SORT_IGNORE = """\
#!/usr/bin/env bash
export LC_ALL=en_US.UTF-8
for f in .*ignore; do
  sort --unique --output="$f" "$f"
done
"""
# update_devenv imports its siblings as top-level modules.
sys.path.insert(0, str(_ROOT / "scripts"))
devenv_common = importlib.import_module("_devenv_common")
update_devenv = importlib.import_module("update_devenv")

pytestmark = pytest.mark.skipif(not _BASH, reason="needs bash")


def _sort_ignore(cwd: Path) -> None:
    subprocess.run(  # noqa: S603
        [_BASH, str(_SORT_IGNORE)], cwd=cwd, check=True, capture_output=True
    )


@pytest.mark.parametrize(
    ("text", "sorted_text"),
    [
        ("c\na\nb\na\n", "a\nb\nc\n"),
        ("!b\n!a\n!b\n", "!a\n!b\n"),
        ("!b\nz\n!a\na\nz\n", "a\nz\n!a\n!b\n"),
        # An escaped "!" is a pattern for a name that starts with "!".
        ("!x\n\\!y\n", "\\!y\n!x\n"),
        ("b\na", "a\nb\n"),
        ("", ""),
    ],
)
def test_sorts_patterns_then_negations(
    tmp_path: Path, text: str, sorted_text: str
) -> None:
    """Patterns and negations are each sorted and deduplicated."""
    (tmp_path / ".gitignore").write_text(text)

    _sort_ignore(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == sorted_text


def test_sorts_every_ignore_file(tmp_path: Path) -> None:
    """Each .*ignore file in the directory is sorted."""
    (tmp_path / ".dockerignore").write_text("!keep\nd*\n")
    (tmp_path / ".prettierignore").write_text("b\na\n")
    (tmp_path / "notes").write_text("b\na\n")

    _sort_ignore(tmp_path)

    assert (tmp_path / ".dockerignore").read_text() == "d*\n!keep\n"
    assert (tmp_path / ".prettierignore").read_text() == "a\nb\n"
    assert (tmp_path / "notes").read_text() == "b\na\n"


def test_keeps_the_file_mode(tmp_path: Path) -> None:
    """The file is rewritten in place, not replaced."""
    path = tmp_path / ".gitignore"
    mode = 0o640
    path.write_text("b\na\n")
    path.chmod(mode)

    _sort_ignore(tmp_path)

    assert path.stat().st_mode & 0o777 == mode


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_unreadable_file_is_left_alone(tmp_path: Path) -> None:
    """A file it can write but not read fails the run instead of emptying."""
    path = tmp_path / ".gitignore"
    path.write_text("b\na\n")
    path.chmod(0o200)

    result = subprocess.run(  # noqa: S603
        [_BASH, str(_SORT_IGNORE)], cwd=tmp_path, check=False, capture_output=True
    )

    path.chmod(0o644)
    assert result.returncode != 0
    assert path.read_text() == "b\na\n"


def test_skips_symlinks(tmp_path: Path) -> None:
    """A symlinked ignore file belongs to whatever it points at."""
    shared = tmp_path / "shared"
    shared.write_text("b\na\n")
    (tmp_path / ".gitignore").symlink_to(shared)

    _sort_ignore(tmp_path)

    assert shared.read_text() == "b\na\n"


def test_no_ignore_files_creates_none(tmp_path: Path) -> None:
    """An unmatched .*ignore glob is not taken for a file name."""
    _sort_ignore(tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not _GIT, reason="needs git")
def test_negation_overrides_a_pattern_once_sorted(tmp_path: Path) -> None:
    """Sorted, washboard's "!frontend/src/lib/" keeps its dir out of "lib/"."""
    for name in ("frontend/src/lib/a.ts", "lib/b.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("")
    (tmp_path / ".gitignore").write_text("!frontend/src/lib/\nlib/\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, env=env, check=True)  # noqa: S603

    _sort_ignore(tmp_path)

    ignored = subprocess.run(  # noqa: S603
        [_GIT, "check-ignore", "--no-index", "frontend/src/lib/a.ts", "lib/b.py"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.stdout.splitlines() == ["lib/b.py"]


def test_update_devenv_sorts_with_the_copied_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project's old sort-ignore.sh, which put negations first, never runs."""
    src = tmp_path / "devenv"
    (src / "merge" / "common").mkdir(parents=True)
    (src / "merge" / "common" / ".gitignore").write_text("lib/\n")
    (src / "copy" / "common" / "bin").mkdir(parents=True)
    shutil.copy2(_SORT_IGNORE, src / "copy" / "common" / "bin" / "sort-ignore.sh")
    project = tmp_path / "project"
    (project / "bin").mkdir(parents=True)
    old_script = project / "bin" / "sort-ignore.sh"
    old_script.write_text(_OLD_SORT_IGNORE)
    old_script.chmod(0o755)
    (project / ".gitignore").write_text("!frontend/src/lib/\n")

    def run_only_sort_ignore(cmd: list[str | Path], **kwargs: object) -> None:
        if cmd == ["bin/sort-ignore.sh"]:
            devenv_common.run(cmd, **kwargs)

    monkeypatch.chdir(project)
    monkeypatch.setenv("DEVENV_SRC", str(src))
    for feature in devenv_common.ALL_FEATURES:
        monkeypatch.delenv(f"DEVENV_{feature.upper()}", raising=False)
    monkeypatch.setenv("DEVENV_COMMON", "1")
    monkeypatch.setattr(update_devenv, "run", run_only_sort_ignore)

    update_devenv.main()

    assert (project / ".gitignore").read_text() == "lib/\n!frontend/src/lib/\n"
