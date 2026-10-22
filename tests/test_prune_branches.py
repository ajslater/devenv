"""
copy/common/bin/prune-branches.sh against a throwaway git repo.

It deletes every local branch but main, master, develop, pre-release, those
named in .keep-branches and those checked out in a worktree.
"""

import os
import shutil
lazy from pathlib import Path

import pytest

from tests.bin_project import USAGE_EXIT
lazy from tests.bin_project import Project

_GIT = shutil.which("git") or ""
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Prune Test",
    "GIT_AUTHOR_EMAIL": "prune@example.com",
    "GIT_COMMITTER_NAME": "Prune Test",
    "GIT_COMMITTER_EMAIL": "prune@example.com",
    # Keep the developer's own git config (signing, hooks, aliases) out.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
_STANDARD = {"main", "master", "develop", "pre-release"}

pytestmark = pytest.mark.skipif(not _GIT, reason="needs git")


def _git(repo: Project, *args: str) -> str:
    result = repo.run("git", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _branches(repo: Project) -> set[str]:
    refs = _git(repo, "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads")
    return set(refs.split())


def _branch(repo: Project, *names: str) -> None:
    for name in names:
        _git(repo, "branch", name)


@pytest.fixture
def repo(project: Project) -> Project:
    """Build a repo on main, with one commit and the script installed."""
    (project.fakebin / "git").symlink_to(_GIT)
    for key in [key for key in project.env if key.startswith("GIT_")]:
        del project.env[key]
    project.env.update(_GIT_ENV)
    project.install("common/prune-branches.sh")
    _git(project, "init", "-q", "-b", "main")
    _git(project, "commit", "-q", "--allow-empty", "-m", "first")
    return project


def test_keeps_only_the_standard_branches(repo: Project) -> None:
    """main, master, develop and pre-release survive; the rest go."""
    _branch(repo, "master", "develop", "pre-release", "feature", "fix/thing")

    result = repo.script("prune-branches.sh")

    assert result.returncode == 0, result.stderr
    assert _branches(repo) == _STANDARD
    assert "Deleted branch feature" in result.stdout
    assert "Deleted branch fix/thing" in result.stdout


def test_keeps_the_branches_in_keep_branches(repo: Project) -> None:
    """Names and globs, past comments, blanks, whitespace and CRLF endings."""
    (repo.root / ".keep-branches").write_bytes(
        b"# comment\n\n  spaced  \ncrlf  \r\nrelease/*  # why\nlast"
    )
    _branch(repo, "spaced", "crlf", "release/1", "release/2", "last")
    _branch(repo, "releases", "gone", "comment", "why")

    result = repo.script("prune-branches.sh")

    assert result.returncode == 0, result.stderr
    assert _branches(repo) == {
        "main",
        "spaced",
        "crlf",
        "release/1",
        "release/2",
        "last",
    }


def test_keeps_the_branches_checked_out_in_worktrees(
    repo: Project, tmp_path: Path
) -> None:
    """The * and + branches of git branch stay, whatever their names."""
    _git(repo, "worktree", "add", "-q", str(tmp_path / "linked"), "-b", "linked")
    _git(repo, "switch", "-q", "-c", "current")
    _branch(repo, "idle")

    result = repo.script("prune-branches.sh")

    assert result.returncode == 0, result.stderr
    assert _branches(repo) == {"main", "current", "linked"}


def test_keeps_unmerged_branches_without_f(repo: Project) -> None:
    """Unmerged work is kept and the run fails; -f deletes it."""
    _git(repo, "switch", "-q", "-c", "wip")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "work in progress")
    _git(repo, "switch", "-q", "main")
    _branch(repo, "merged")

    result = repo.script("prune-branches.sh")

    assert result.returncode == 1
    assert "-f deletes them too" in result.stderr
    assert _branches(repo) == {"main", "wip"}

    result = repo.script("prune-branches.sh", "-f")

    assert result.returncode == 0, result.stderr
    assert _branches(repo) == {"main"}


def test_n_deletes_nothing(repo: Project) -> None:
    """-n lists what it would delete."""
    _branch(repo, "a", "b", "develop")

    result = repo.script("prune-branches.sh", "-n")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["Would delete a", "Would delete b"]
    assert _branches(repo) == {"main", "a", "b", "develop"}


def test_nothing_to_delete(repo: Project) -> None:
    """An empty list is no error, even under bash 3.2's set -u."""
    result = repo.script("prune-branches.sh")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "No branches to delete.\n"


def test_reads_keep_branches_at_the_root(repo: Project) -> None:
    """Run from a subdirectory, it still keeps what the root's file names."""
    (repo.root / ".keep-branches").write_text("kept\n")
    (repo.root / "sub").mkdir()
    _branch(repo, "kept", "gone")

    result = repo.run("sh", "-c", "cd sub && exec ../bin/prune-branches.sh")

    assert result.returncode == 0, result.stderr
    assert _branches(repo) == {"main", "kept"}


@pytest.mark.parametrize("args", [["-x"], ["extra"], ["-n", "extra"]])
def test_rejects_unknown_arguments(repo: Project, args: list[str]) -> None:
    """A typo is a usage error, not a run that deletes branches."""
    _branch(repo, "feature")

    result = repo.script("prune-branches.sh", *args)

    assert result.returncode == USAGE_EXIT
    assert "usage:" in result.stderr
    assert _branches(repo) == {"main", "feature"}
