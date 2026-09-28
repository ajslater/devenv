"""
The devenv CI building blocks in copy/ci/.github.

Structural invariants that keep the gate, the fail-fast matrix and the
required-check aggregator honest, then actionlint over a child repo assembled
from copy/ and a fixture caller: the standard one, and a codex-shaped one with
its own jobs between ci and release.
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
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gha"
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
        assert "continue-on-error" not in job, job_id
    for job_id, step in _all_steps():
        assert "continue-on-error" not in step, (job_id, step)


def test_default_matrix() -> None:
    """Lint writes the cache, Test publishes junit, Build Dist uploads the dist."""
    matrix = json.loads(_CALL["inputs"]["matrix"]["default"])
    assert [(combo["name"], combo["make"]) for combo in matrix] == [
        ("Lint", "lint"),
        ("Test", "test"),
        ("Build Dist", "build"),
    ]
    lint, test, build = matrix
    for flag, owner in (("write-cache", lint), ("junit", test), ("dist", build)):
        assert [combo for combo in matrix if combo.get(flag)] == [owner], flag


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
@pytest.mark.parametrize("caller", ["std-ci.yml", "codex-ci.yml"])
def test_actionlint_child_repo(tmp_path: Path, caller: str) -> None:
    """Every workflow lints, including each caller's use of the devenv blocks."""
    repo = _child_repo(tmp_path, (_FIXTURES / caller).read_text())

    result = _actionlint(repo)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not (_ACTIONLINT and _GIT), reason="needs actionlint and git")
def test_actionlint_checks_the_call_contract(tmp_path: Path) -> None:
    """An unknown input or output in a caller fails, so the test above means something."""
    caller = (_FIXTURES / "std-ci.yml").read_text()
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
