"""
The rules every caller of devenv-check follows.

The standard copy/gha_std ci.yml and codex- and native-shaped fixtures with
their own jobs between ci and release, and what PyPI trusted publishing needs
from them.
"""

from typing import Any

import pytest

from tests.gha import ACTIONS, CALLERS, STD_CALLER, WORKFLOWS, load, trigger

_CALL_CHECK = "./.github/workflows/devenv-check.yml"
_CALL_RELEASE = "./.github/workflows/devenv-release.yml"
_PYPI = "./.github/actions/devenv-pypi"


# ---------------------------------------------------------------------------
# Callers: copy/gha_std's ci.yml and a codex-shaped fixture
# ---------------------------------------------------------------------------


def _caller_jobs(name: str) -> dict[str, dict[str, Any]]:
    return load(CALLERS[name])["jobs"]


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else needs


def _downstream(jobs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return every job that runs after the check."""
    return {
        job_id: job for job_id, job in jobs.items() if job.get("uses") != _CALL_CHECK
    }


def _ancestors(jobs: dict[str, dict[str, Any]], job_id: str) -> set[str]:
    found: set[str] = set()
    todo = _needs(jobs[job_id])
    while todo:
        need = todo.pop()
        if need not in found:
            found.add(need)
            todo.extend(_needs(jobs[need]))
    return found


def test_std_caller_is_managed() -> None:
    """
    The standard caller runs on main pushes and PRs into main or develop.

    Only a pull request's run is cancelled by a newer push: cancelling a main
    run could cut between the PyPI publish and the tag.
    """
    text = STD_CALLER.read_text()
    assert text.startswith("# Managed by devenv (copy/gha_std).")
    workflow = load(STD_CALLER)
    assert trigger(workflow) == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main", "develop"]},
    }
    assert workflow["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )


@pytest.mark.parametrize("name", CALLERS)
def test_caller_runs_the_check_once_as_ci(name: str) -> None:
    """One ci job calls devenv-check with the permissions its jobs need."""
    jobs = _caller_jobs(name)
    checks = [job_id for job_id, job in jobs.items() if job.get("uses") == _CALL_CHECK]
    assert checks == ["ci"]
    assert jobs["ci"]["name"] == "CI"
    assert jobs["ci"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "packages": "write",
        "checks": "write",
    }


@pytest.mark.parametrize("name", CALLERS)
def test_caller_downstream_jobs_need_explicit_success(name: str) -> None:
    """
    Every later job checks !cancelled() and an explicit result.

    The implicit success() skips a job after any skipped ancestor, and
    !failure() ignores cancelled ones.
    """
    for job_id, job in _downstream(_caller_jobs(name)).items():
        condition = job["if"]
        assert "!cancelled()" in condition, job_id
        for need in [need for need in _needs(job) if need != "ci"] or ["ci"]:
            assert f"needs.{need}.result ==" in condition, (job_id, need)


@pytest.mark.parametrize("name", CALLERS)
def test_caller_triggers_come_from_ci(name: str) -> None:
    """Later jobs read the gate's outputs and never test the event themselves."""
    for job_id, job in _downstream(_caller_jobs(name)).items():
        assert "ci" in _needs(job), job_id
        for event_test in ("github.event_name", "github.ref", "base_ref", "head_ref"):
            assert event_test not in job["if"], (job_id, event_test)
        if _needs(job) == ["ci"]:
            assert "needs.ci.outputs.deploy == 'true'" in job["if"], job_id


@pytest.mark.parametrize("name", CALLERS)
def test_caller_release_runs_last(name: str) -> None:
    """The release waits for every deploy job and only runs on outputs.release."""
    jobs = _caller_jobs(name)
    releases = [
        job_id for job_id, job in jobs.items() if job.get("uses") == _CALL_RELEASE
    ]
    assert len(releases) == 1
    (release_id,) = releases
    release = jobs[release_id]
    assert "needs.ci.outputs.release == 'true'" in release["if"]
    assert release["permissions"] == {"contents": "write"}
    deploy_jobs = set(_downstream(jobs)) - {release_id}
    assert deploy_jobs <= _ancestors(jobs, release_id)


# ---------------------------------------------------------------------------
# devenv-pypi: a token while one is passed, trusted publishing without
# ---------------------------------------------------------------------------


def _pypi_jobs(jobs: dict[str, dict[str, Any]]) -> list[str]:
    return [
        job_id
        for job_id, job in jobs.items()
        if any(step.get("uses") == _PYPI for step in job.get("steps", []))
    ]


def _pypi_publishes(action: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the action's uv publish steps keyed by their condition."""
    return {
        step["if"]: step
        for step in action["runs"]["steps"]
        if step.get("run", "").startswith("uv publish ")
    }


def test_pypi_publishes_with_a_token_or_trusted_publishing() -> None:
    """
    A passed token publishes as before; an empty one means trusted publishing.

    A caller's secrets.PYPI_TOKEN is empty once the secret is deleted, so each
    repo switches when its secret goes. UV_PUBLISH_TOKEN must then stay unset.
    """
    action = load(ACTIONS / "devenv-pypi" / "action.yml")
    token = action["inputs"]["token"]
    assert token["required"] is False
    assert token["default"] == ""
    publishes = _pypi_publishes(action)
    assert set(publishes) == {"inputs.token != ''", "inputs.token == ''"}
    with_token = publishes["inputs.token != ''"]
    assert with_token["env"] == {"UV_PUBLISH_TOKEN": "${{ inputs.token }}"}
    trusted = publishes["inputs.token == ''"]
    assert "env" not in trusted
    assert "--trusted-publishing always" in trusted["run"]
    for step in publishes.values():
        assert step["run"].endswith(" --check-url https://pypi.org/simple/ dist/*")


@pytest.mark.parametrize("name", CALLERS)
def test_caller_pypi_job_can_get_an_identity_token(name: str) -> None:
    """Trusted publishing fails at the token exchange without id-token: write."""
    jobs = _caller_jobs(name)
    publishers = _pypi_jobs(jobs)
    assert publishers
    for job_id in publishers:
        assert jobs[job_id]["permissions"]["id-token"] == "write", job_id


def test_only_ci_yml_publishes_to_pypi() -> None:
    """
    The publish runs in ci.yml itself, never in a reusable workflow.

    Each PyPI publisher names ci.yml, and PyPI refuses trusted publishing from
    inside a reusable workflow.
    """
    assert STD_CALLER.name == "ci.yml"
    for path in WORKFLOWS.glob("devenv-*.yml"):
        assert not _pypi_jobs(load(path)["jobs"]), path
