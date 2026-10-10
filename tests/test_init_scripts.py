"""
init-project.sh and convert-project.sh in scratch directories.

make is stubbed to record its arguments, so the first update-devenv the
scripts end with does not install node packages. add_features runs for real.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BASH = shutil.which("bash") or "bash"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("uv") and shutil.which("git")),
    reason="needs bash, uv and git",
)


def _run(script: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    stubs = cwd.parent / "stubs"
    stubs.mkdir(exist_ok=True)
    make = stubs / "make"
    make.write_text(f'#!/bin/sh\necho "$@" > "{stubs}/make.args"\n')
    make.chmod(make.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
    env.pop("DEVENV_SRC", None)
    return subprocess.run(  # noqa: S603
        [_BASH, str(_ROOT / "scripts" / script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return an empty project dir."""
    path = tmp_path / "project"
    path.mkdir()
    return path


def test_init_sets_up_a_new_project(project: Path) -> None:
    """A new dir gets git, starters, feature makefiles and an update."""
    result = _run("init-project.sh", project, "docs")

    assert result.returncode == 0, result.stderr
    assert (project / ".git").is_dir()
    makefile = (project / "Makefile").read_text()
    assert "include cfg/docs.mk\n" in makefile
    assert "# include cfg/docs.mk" not in makefile
    assert (project / "eslint.config.js").is_file()
    assert 'requires-python = ">=3.15"' in (project / "pyproject.toml").read_text()
    assert (project.parent / "stubs" / "make.args").read_text() == (
        f"update-devenv DEVENV_SRC={_ROOT}\n"
    )


def test_init_without_node_does_not_fail(project: Path) -> None:
    """The eslint starter is optional, not a hard `mv` that exits 1."""
    result = _run("init-project.sh", project)

    assert result.returncode == 0, result.stderr


def test_init_rejects_an_unmet_requirement_before_changing_files(
    project: Path,
) -> None:
    """gha_std without ci stops with one line, leaving only git behind."""
    result = _run("init-project.sh", project, "gha_std")

    assert result.returncode != 0
    assert "'gha_std' requires 'ci'" in result.stderr
    assert [path.name for path in project.iterdir()] == [".git"]


def test_convert_an_existing_python_project(project: Path) -> None:
    """An initialized python project converts; its own files stay."""
    (project / "Makefile").write_text("old:\n\techo old\n")
    (project / "pyproject.toml").write_text('[project]\nname = "old"\n')
    (project / "README.md").write_text("# Old\n")

    result = _run("convert-project.sh", project)

    assert result.returncode == 0, result.stderr
    assert (project / "Makefile.orig.mk").read_text() == "old:\n\techo old\n"
    assert "include cfg/common.mk" in (project / "Makefile").read_text()
    assert (project / "pyproject.toml").read_text() == '[project]\nname = "old"\n'
    assert (project / "README.md").read_text() == "# Old\n"
