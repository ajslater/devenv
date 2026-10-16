"""
Hardening in every .github devenv ships or runs, and actionlint over them.

Actions are pinned by commit SHA and every job has a timeout. actionlint runs
over a child repo assembled from copy/ with each caller and over devenv's own
CI.
"""

import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from tests.gha import CALLERS, CI, ROOT, STD_CALLER, load

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_DEVENV_CI = ROOT / ".github" / "workflows" / "ci.yml"
# Every .github devenv ships or runs; the fixtures model other repos.
_GITHUB_DIRS = (CI / ".github", STD_CALLER.parent.parent, _DEVENV_CI.parent.parent)
_ACTIONLINT = shutil.which("actionlint") or ""
_GIT = shutil.which("git") or ""


# ---------------------------------------------------------------------------
# Hardening in every .github devenv ships or runs
# ---------------------------------------------------------------------------


_USES_LINE = re.compile(r"^\s*(?:- )?uses: (\S+)(.*)$", re.MULTILINE)
_SHA_PIN = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")
_TAG_COMMENT = re.compile(r" # v\d+\.\d+\.\d+")
_MAX_TIMEOUT_MINUTES = 60


def _github_files() -> list[Path]:
    return sorted(path for root in _GITHUB_DIRS for path in root.rglob("*.yml"))


def _uses_values(node: Any) -> Iterator[str]:
    """Yield every uses: value in a parsed workflow or action."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses":
                yield value
            else:
                yield from _uses_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _uses_values(item)


def test_third_party_actions_are_pinned_by_sha() -> None:
    """
    A tag can be moved to other code; a commit SHA cannot.

    The trailing "# vX.Y.Z" names the release for readers and Dependabot.
    Each action has one pin everywhere, so a bump cannot half-apply.
    """
    pins: dict[str, set[str]] = {}
    for path in _github_files():
        lines = _USES_LINE.findall(path.read_text())
        # The line scan sees every uses: the parser does, comments included.
        assert sorted(ref for ref, _ in lines) == sorted(_uses_values(load(path)))
        for ref, comment in lines:
            if ref.startswith("./"):
                continue
            assert _SHA_PIN.fullmatch(ref), (path, ref)
            assert _TAG_COMMENT.fullmatch(comment), (path, ref, comment)
            action, _, sha = ref.partition("@")
            pins.setdefault(action, set()).add(sha + comment)
    assert pins
    for action, found in pins.items():
        assert len(found) == 1, (action, found)


def test_every_job_has_a_timeout() -> None:
    """
    A hung job otherwise holds its runner for GitHub's default six hours.

    A job that calls a reusable workflow cannot set one; its jobs do.
    """
    jobs = [
        (path, job_id, job)
        for path in _github_files()
        for job_id, job in load(path).get("jobs", {}).items()
        if "uses" not in job
    ]
    check_jobs = {job_id for path, job_id, _ in jobs if path.name == "devenv-check.yml"}
    assert {"gate", "image", "check", "result"} <= check_jobs
    for path, job_id, job in jobs:
        timeout = job.get("timeout-minutes")
        assert isinstance(timeout, int), (path, job_id)
        assert 0 < timeout <= _MAX_TIMEOUT_MINUTES, (path, job_id, timeout)


# ---------------------------------------------------------------------------
# actionlint over a child repo and devenv's own CI
# ---------------------------------------------------------------------------


def _child_repo(tmp_path: Path, caller: str) -> Path:
    """Lay out copy/ci and copy/python/bin the way update-devenv would."""
    repo = tmp_path / "child"
    CI.copy(repo, preserve_metadata=True)
    shutil.copytree(ROOT / "copy" / "python" / "bin", repo / "bin", dirs_exist_ok=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(caller)
    subprocess.run([_GIT, "init", "-q"], cwd=repo, check=True)  # noqa: S603
    return repo


def _actionlint(repo: Path, *files: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_ACTIONLINT, "-no-color", *files],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not (_ACTIONLINT and _GIT), reason="needs actionlint and git")
@pytest.mark.parametrize("name", CALLERS)
def test_actionlint_child_repo(tmp_path: Path, name: str) -> None:
    """Every workflow lints, including each caller's use of the devenv blocks."""
    repo = _child_repo(tmp_path, CALLERS[name].read_text())

    result = _actionlint(repo)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not (_ACTIONLINT and _GIT), reason="needs actionlint and git")
def test_actionlint_checks_the_call_contract(tmp_path: Path) -> None:
    """An unknown input or output in a caller fails, so the test above means something."""
    caller = STD_CALLER.read_text()
    caller = caller.replace("outputs.deploy ==", "outputs.deploy_it ==")
    caller = caller.replace(
        "uses: ./.github/workflows/devenv-check.yml",
        "uses: ./.github/workflows/devenv-check.yml\n    with:\n      bogus: x",
    )
    repo = _child_repo(tmp_path, caller)

    result = _actionlint(repo)

    assert result.returncode == 1
    assert 'input "bogus" is not defined' in result.stdout
    assert 'property "deploy_it" is not defined' in result.stdout


@pytest.mark.skipif(not _ACTIONLINT, reason="needs actionlint")
def test_actionlint_devenv_ci() -> None:
    """The repo's own workflow lints too; the ci feature that would lint it is off here."""
    result = _actionlint(ROOT, _DEVENV_CI)

    assert result.returncode == 0, result.stdout + result.stderr
