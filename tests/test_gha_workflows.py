"""
The devenv CI building blocks in copy/ci/.github and their callers.

Structural invariants that keep the gate, the fail-fast matrix and the
required-check aggregator honest, the rules every caller follows (the
standard copy/gha_std ci.yml and a codex-shaped fixture with its own jobs
between ci and release), then actionlint over a child repo assembled from
copy/ with each caller.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

_ROOT = Path(__file__).resolve().parent.parent
_CI = _ROOT / "copy" / "ci"
_WORKFLOWS = _CI / ".github" / "workflows"
_ACTIONS = _CI / ".github" / "actions"
_STD_CALLER = _ROOT / "copy" / "gha_std" / ".github" / "workflows" / "ci.yml"
_CALLERS = {
    "std": _STD_CALLER,
    "codex": Path(__file__).resolve().parent / "fixtures" / "gha" / "codex-ci.yml",
    "native": Path(__file__).resolve().parent / "fixtures" / "gha" / "native-ci.yml",
}
_CALL_CHECK = "./.github/workflows/devenv-check.yml"
_CALL_RELEASE = "./.github/workflows/devenv-release.yml"
_REUSE_SCRIPT = _CI / "bin" / "ci-reuse-dist.sh"
_MANAGED = "# Managed by devenv (copy/ci)."
_REQUIRED_CHECK = "Lint, Test & Build Dist"
_MAIN_PUSH = "github.event_name == 'push' && github.ref_name == 'main'"
_ACTIONLINT = shutil.which("actionlint") or ""
_GIT = shutil.which("git") or ""


def _load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text())


def _trigger(workflow: dict[Any, Any]) -> Any:
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow[True]


_CHECK = _load(_WORKFLOWS / "devenv-check.yml")
_RELEASE = _load(_WORKFLOWS / "devenv-release.yml")
_JOBS = _CHECK["jobs"]
_CALL = _trigger(_CHECK)["workflow_call"]


def _steps(job_id: str) -> list[dict[str, Any]]:
    return _JOBS[job_id]["steps"]


def _all_steps() -> Iterator[tuple[str, dict[str, Any]]]:
    for job_id, job in _JOBS.items():
        for step in job["steps"]:
            yield job_id, step


# ---------------------------------------------------------------------------
# devenv-check.yml
# ---------------------------------------------------------------------------


def test_every_managed_file_says_so() -> None:
    """A child repo's copy tells you to edit it in devenv instead."""
    managed = [*_WORKFLOWS.glob("devenv-*.yml"), *_ACTIONS.glob("devenv-*/action.yml")]
    assert len(managed) == 4  # noqa: PLR2004
    for path in managed:
        assert path.read_text().startswith(_MANAGED), path


def test_check_matrix_fails_fast() -> None:
    """The first failing combo cancels the rest; nothing may swallow a failure."""
    check = _JOBS["check"]
    assert check["strategy"]["fail-fast"] is True
    assert check["strategy"]["matrix"]["include"] == "${{ fromJSON(inputs.matrix) }}"
    assert check["name"] == "${{ matrix.name }}"
    for job_id, job in _JOBS.items():
        # Only the housekeeping prune may fail without failing CI.
        assert ("continue-on-error" in job) == (job_id == "prune"), job_id
    for job_id, step in _all_steps():
        assert "continue-on-error" not in step, (job_id, step)


def test_default_matrix() -> None:
    """Test publishes junit and Build Dist uploads the dist."""
    matrix = json.loads(_CALL["inputs"]["matrix"]["default"])
    assert [(combo["name"], combo["make"]) for combo in matrix] == [
        ("Lint", "lint"),
        ("Test", "test"),
        ("Build Dist", "build"),
    ]
    _, test, build = matrix
    for flag, owner in (("junit", test), ("dist", build)):
        assert [combo for combo in matrix if combo.get(flag)] == [owner], flag


def _uses(prefix: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (job_id, step)
        for job_id, step in _all_steps()
        if step.get("uses", "").startswith(prefix)
    ]


def test_ci_image_is_built_once_and_pulled() -> None:
    """One job builds and pushes the image by digest; each combo pulls it."""
    ((job_id, build),) = _uses("docker/build-push-action@")
    assert job_id == "image"
    options = build["with"]
    assert "push-by-digest=true" in options["outputs"]
    assert "push=true" in options["outputs"]
    assert "load" not in options
    assert options["cache-to"].startswith("type=registry,")
    assert options["provenance"] is False
    assert _JOBS["image"]["outputs"]["image"] == "${{ steps.ref.outputs.image }}"
    check = _JOBS["check"]
    assert check["needs"] == ["gate", "image"]
    assert check["permissions"]["packages"] == "read"
    ((_, start),) = _uses("./.github/actions/devenv-ci-container")
    assert start["with"] == {"image": "${{ needs.image.outputs.image }}"}
    container = (_ACTIONS / "devenv-ci-container" / "action.yml").read_text()
    assert "build-push-action" not in container
    assert 'docker pull --quiet "$CI_IMAGE"' in container
    assert "Re-run all jobs" in container
    assert "--no-build" in container


def test_check_waits_for_the_gate_and_image() -> None:
    """
    Check runs only after a passing gate that reused nothing.

    In container mode the image must have succeeded; only native mode may
    skip it. !cancelled() is needed because the image is skipped there.
    """
    condition = _JOBS["check"]["if"]
    assert "!cancelled()" in condition
    assert "needs.gate.result == 'success'" in condition
    assert "needs.gate.outputs.dist_found != 'true'" in condition
    assert "needs.image.result == 'success'" in condition
    assert "!inputs.container && needs.image.result == 'skipped'" in condition


def test_native_mode() -> None:
    """container: false skips the image and runs make on inputs.runner."""
    inputs = _CALL["inputs"]
    assert inputs["container"]["default"] is True
    assert inputs["runner"]["default"] == "ubuntu-24.04"
    assert _JOBS["image"]["if"].startswith("inputs.container && ")
    check = _JOBS["check"]
    assert check["runs-on"] == "${{ inputs.runner }}"
    for job_id in ("gate", "image", "prune", "result"):
        assert _JOBS[job_id]["runs-on"] == "ubuntu-24.04", job_id
    steps = {step.get("name"): step for step in check["steps"]}
    assert steps["Start CI container"]["if"] == "inputs.container"
    for name in ("Set up uv", "Set up bun", "Install"):
        assert steps[name]["if"] == "${{ !inputs.container }}", name
    assert "make install" in steps["Install"]["run"]
    work = steps["${{ matrix.name }}"]
    assert work["env"]["IN_CONTAINER"] == "${{ inputs.container }}"
    assert 'docker exec "$CI_CONTAINER" make "${targets[@]}"' in work["run"]
    assert '\n  make "${targets[@]}"\n' in work["run"]


def test_prune_keeps_recent_untagged_images() -> None:
    """Pruning deletes only untagged CI images and keeps the newest ones."""
    prune = _JOBS["prune"]
    assert prune["needs"] == "image"
    assert prune["continue-on-error"] is True
    ((job_id, step),) = _uses("actions/delete-package-versions@")
    assert job_id == "prune"
    assert step["with"]["package-name"] == "${{ github.event.repository.name }}-ci"
    assert step["with"]["delete-only-untagged-versions"] == "true"
    # This run's image plus spares for "Re-run failed jobs", without hoarding.
    assert 2 <= step["with"]["min-versions-to-keep"] <= 10  # noqa: PLR2004


def test_required_check_aggregates_the_gate_and_matrix() -> None:
    """always(): a cancelled or skipped check must still turn the result red."""
    result = _JOBS["result"]
    assert result["name"] == _REQUIRED_CHECK
    assert result["needs"] == ["gate", "check"]
    assert "always()" in result["if"]
    assert result["permissions"] == {}


def test_python_dist_has_two_guarded_producers() -> None:
    """Only a reused dist in the gate or a built dist in check is uploaded."""
    producers = {
        job_id: step["if"]
        for job_id, step in _all_steps()
        if step.get("with", {}).get("name") == "python-dist"
    }
    assert producers == {
        "gate": "steps.reuse.outputs.dist_found == 'true'",
        "check": "matrix.dist",
    }


def test_release_preflight_runs_once_in_the_gate() -> None:
    """The preflight runs once per run, after an unconditional checkout."""
    preflights = [
        (job_id, step)
        for job_id, step in _all_steps()
        if step.get("name") == "Release Preflight"
    ]
    assert len(preflights) == 1
    ((job_id, step),) = preflights
    assert job_id == "gate"
    assert step["run"] == "bin/release-tag.sh preflight"
    assert "inputs.release-preflight" in step["if"]
    assert "vars.RELEASE_AUTOMATION != 'off'" in step["if"]
    first = _steps("gate")[0]
    assert first["uses"].startswith("actions/checkout@")
    assert "if" not in first


def test_dist_reuse_is_main_push_only() -> None:
    """A pull request always runs the full check."""
    (reuse,) = [step for step in _steps("gate") if step.get("id") == "reuse"]
    assert reuse["if"] == _MAIN_PUSH
    assert reuse["run"] == "bin/ci-reuse-dist.sh"


def test_marker_names_agree() -> None:
    """The result job's marker is the artifact the reuse script looks up."""
    (upload,) = [
        step
        for step in _steps("result")
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert upload["with"]["name"] == "ci-passed-${{ needs.gate.outputs.tree }}"
    assert _JOBS["gate"]["outputs"]["tree"] == "${{ steps.info.outputs.tree }}"
    script = _REUSE_SCRIPT.read_text()
    assert 'MARKER="ci-passed-$TREE"' in script
    assert "--name python-dist" in script


def test_outputs_come_from_the_gate() -> None:
    """The gate is the only job with trigger logic, so it owns every output."""
    gate_outputs = _JOBS["gate"]["outputs"]
    assert set(_CALL["outputs"]) == set(gate_outputs)
    for name, output in _CALL["outputs"].items():
        assert output["value"] == f"${{{{ jobs.gate.outputs.{name} }}}}"


def test_deploy_and_release_triggers() -> None:
    """Deploy on main pushes and pre-release PRs; release on main pushes only."""
    outputs = _JOBS["gate"]["outputs"]
    assert (
        "(github.event_name == 'push' && github.ref_name == 'main')"
        in (outputs["deploy"])
    )
    assert "github.head_ref == 'pre-release'" in outputs["deploy"]
    assert _MAIN_PUSH in outputs["release"]
    assert "vars.RELEASE_AUTOMATION != 'off'" in outputs["release"]
    assert "base_ref" not in outputs["release"]


# ---------------------------------------------------------------------------
# devenv-release.yml
# ---------------------------------------------------------------------------


def test_release_workflow() -> None:
    """One job: full-history checkout, then tag, publish and merge-back."""
    assert _trigger(_RELEASE) == "workflow_call"
    (job,) = _RELEASE["jobs"].values()
    assert job["permissions"] == {"contents": "write"}
    checkout, *steps = job["steps"]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0
    assert [step["run"] for step in steps] == [
        "bin/release-tag.sh tag",
        "bin/release-tag.sh publish",
        "bin/release-tag.sh merge-back",
    ]


# ---------------------------------------------------------------------------
# Callers: copy/gha_std's ci.yml and a codex-shaped fixture
# ---------------------------------------------------------------------------


def _caller_jobs(name: str) -> dict[str, dict[str, Any]]:
    return _load(_CALLERS[name])["jobs"]


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
    """The standard caller runs on main pushes and PRs into main or develop."""
    text = _STD_CALLER.read_text()
    assert text.startswith("# Managed by devenv (copy/gha_std).")
    workflow = _load(_STD_CALLER)
    assert _trigger(workflow) == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main", "develop"]},
    }
    assert workflow["concurrency"]["cancel-in-progress"] is True


@pytest.mark.parametrize("name", _CALLERS)
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


@pytest.mark.parametrize("name", _CALLERS)
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


@pytest.mark.parametrize("name", _CALLERS)
def test_caller_triggers_come_from_ci(name: str) -> None:
    """Later jobs read the gate's outputs and never test the event themselves."""
    for job_id, job in _downstream(_caller_jobs(name)).items():
        assert "ci" in _needs(job), job_id
        for event_test in ("github.event_name", "github.ref", "base_ref", "head_ref"):
            assert event_test not in job["if"], (job_id, event_test)
        if _needs(job) == ["ci"]:
            assert "needs.ci.outputs.deploy == 'true'" in job["if"], job_id


@pytest.mark.parametrize("name", _CALLERS)
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
# actionlint over a child repo
# ---------------------------------------------------------------------------


def _child_repo(tmp_path: Path, caller: str) -> Path:
    """Lay out copy/ci and copy/python/bin the way update-devenv would."""
    repo = tmp_path / "child"
    shutil.copytree(_CI, repo)
    shutil.copytree(_ROOT / "copy" / "python" / "bin", repo / "bin", dirs_exist_ok=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(caller)
    subprocess.run([_GIT, "init", "-q"], cwd=repo, check=True)  # noqa: S603
    return repo


def _actionlint(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_ACTIONLINT, "-no-color"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not (_ACTIONLINT and _GIT), reason="needs actionlint and git")
@pytest.mark.parametrize("name", _CALLERS)
def test_actionlint_child_repo(tmp_path: Path, name: str) -> None:
    """Every workflow lints, including each caller's use of the devenv blocks."""
    repo = _child_repo(tmp_path, _CALLERS[name].read_text())

    result = _actionlint(repo)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not (_ACTIONLINT and _GIT), reason="needs actionlint and git")
def test_actionlint_checks_the_call_contract(tmp_path: Path) -> None:
    """An unknown input or output in a caller fails, so the test above means something."""
    caller = _STD_CALLER.read_text()
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
