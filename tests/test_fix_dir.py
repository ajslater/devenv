"""
scripts/fix-dir.sh, which fixes or lints a directory that is not a project.

Fake shell tools and a fake uv log their argv and working directory, so the
tests show which tools run where with which flags. sh-tools.sh runs for real
from devenv's copy/common/bin.
"""

from pathlib import Path

import pytest

from tests.bin_project import FAIL_EXIT, USAGE_EXIT, make_tree
lazy from tests.bin_project import Project

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "fix-dir.sh"
_RUFF = ["run", "--project", str(_ROOT), "--group", "lint", "ruff"]
_SH_TOOLS = ("shellcheck", "shellharden", "shfmt", "uv")


@pytest.fixture
def target(project: Project) -> Path:
    """Return a directory beside the project holding one shell script."""
    path = project.root.parent / "target"
    make_tree(path, "a.sh")
    project.fake(*_SH_TOOLS)
    return path


def test_fix_runs_the_fixers_in_the_directory(project: Project, target: Path) -> None:
    """Fix mode rewrites the scripts, then ruff fixes and formats."""
    result = project.run(_SCRIPT, target)

    assert result.returncode == 0, result.stderr
    assert project.argvs() == [
        ["--replace", "./a.sh"],
        ["--simplify", "--indent", "2", "--write", "./a.sh"],
        [*_RUFF, "check", "--fix", "--exit-zero", "."],
        [*_RUFF, "format", "."],
    ]
    assert {call["cwd"] for call in project.calls()} == {str(target)}


def test_lint_runs_the_checks_in_the_directory(project: Project, target: Path) -> None:
    """Lint mode only checks, and runs shellcheck too."""
    result = project.run(_SCRIPT, "--lint", target)

    assert result.returncode == 0, result.stderr
    assert project.argvs() == [
        ["./a.sh"],
        ["--check", "./a.sh"],
        ["--simplify", "--indent", "2", "--diff", "./a.sh"],
        [*_RUFF, "check", "."],
        [*_RUFF, "format", "--check", "."],
    ]


@pytest.mark.usefixtures("target")
def test_the_directory_defaults_to_the_current_one(project: Project) -> None:
    """With no DIR it works where it is run."""
    make_tree(project.root, "b.sh")

    result = project.run(_SCRIPT)

    assert result.returncode == 0, result.stderr
    assert {call["cwd"] for call in project.calls()} == {str(project.root)}
    assert ["--replace", "./b.sh"] in project.argvs()


def test_a_lint_failure_fails(project: Project, target: Path) -> None:
    """A check that fails gives its status."""
    result = project.run(
        _SCRIPT, "--lint", target, FAKE_FAIL="format", FAKE_FAIL_STATUS=str(FAIL_EXIT)
    )

    assert result.returncode == FAIL_EXIT


@pytest.mark.usefixtures("target")
@pytest.mark.parametrize("args", [("--fixx",), ("a", "b"), ("-h",)])
def test_bad_arguments_print_usage(project: Project, args: tuple[str, ...]) -> None:
    """An unknown option or a second DIR runs nothing."""
    result = project.run(_SCRIPT, *args)

    assert result.returncode == USAGE_EXIT
    assert "usage:" in result.stderr
    assert project.calls() == []
