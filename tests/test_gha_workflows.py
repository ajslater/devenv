"""
The devenv CI building blocks in copy/ci/.github.

Structural invariants that keep the gate, the fail-fast matrix and the
required-check aggregator honest, and the release workflow.
"""

import json
import re
from typing import TYPE_CHECKING, Any

from tests.gha import ACTIONS, CI, WORKFLOWS, load, trigger

if TYPE_CHECKING:
    from collections.abc import Iterator

_REUSE_SCRIPT = CI / "bin" / "ci-reuse-dist.sh"
_MANAGED = "# Managed by devenv (copy/ci)."
_REQUIRED_CHECK = "Lint, Test & Build Dist"
_MAIN_PUSH = "github.event_name == 'push' && github.ref_name == 'main'"

_CHECK = load(WORKFLOWS / "devenv-check.yml")
_RELEASE = load(WORKFLOWS / "devenv-release.yml")
_JOBS = _CHECK["jobs"]
_CALL = trigger(_CHECK)["workflow_call"]


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
    managed = [*WORKFLOWS.glob("devenv-*.yml"), *ACTIONS.glob("devenv-*/action.yml")]
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


def test_ci_image_is_built_once() -> None:
    """One job builds and pushes the image by digest."""
    ((job_id, build),) = _uses("docker/build-push-action@")
    assert job_id == "image"
    options = build["with"]
    assert "push-by-digest=true" in options["outputs"]
    assert "push=true" in options["outputs"]
    assert "load" not in options
    assert options["cache-to"].startswith("type=registry,")
    assert options["provenance"] is False
    assert _JOBS["image"]["outputs"]["image"] == "${{ steps.ref.outputs.image }}"


def test_each_combo_pulls_the_ci_image() -> None:
    """Each combo pulls the image job's image and never builds its own."""
    check = _JOBS["check"]
    assert check["needs"] == ["gate", "image"]
    assert check["permissions"]["packages"] == "read"
    ((_, start),) = _uses("./.github/actions/devenv-ci-container")
    assert start["with"] == {"image": "${{ needs.image.outputs.image }}"}
    container = (ACTIONS / "devenv-ci-container" / "action.yml").read_text()
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
    """container: false skips the image and runs the check on inputs.runner."""
    inputs = _CALL["inputs"]
    assert inputs["container"]["default"] is True
    assert inputs["runner"]["default"] == "ubuntu-latest"
    assert _JOBS["image"]["if"].startswith("inputs.container && ")
    assert _JOBS["check"]["runs-on"] == "${{ inputs.runner }}"
    for job_id in ("gate", "image", "prune", "result"):
        assert _JOBS[job_id]["runs-on"] == "ubuntu-latest", job_id


def test_native_mode_installs_and_runs_make_on_the_runner() -> None:
    """Without the container, the check installs the project and runs make itself."""
    steps = {step.get("name"): step for step in _steps("check")}
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


def test_gate_checks_develop_prs_only_from_release_branches() -> None:
    """
    A pull request into develop is checked from pre-release or v<digit>... only.

    Expressions have no regex, so the gate lists one startsWith per digit; a
    bare 'v' prefix would also run CI for a branch like vulture-fix.
    """
    condition = _JOBS["gate"]["if"]
    assert "github.base_ref == 'develop'" in condition
    assert "github.head_ref == 'pre-release'" in condition
    prefixes = re.findall(r"startsWith\(github\.head_ref, '([^']*)'\)", condition)
    assert sorted(prefixes) == [f"v{digit}" for digit in range(10)]
    for branch, checked in (("v1.2.3", True), ("v10.0", True), ("vulture-fix", False)):
        assert any(branch.startswith(prefix) for prefix in prefixes) is checked, branch


# ---------------------------------------------------------------------------
# devenv-release.yml
# ---------------------------------------------------------------------------


def test_release_workflow() -> None:
    """One job: full-history checkout, then tag, publish and merge-back."""
    assert trigger(_RELEASE) == "workflow_call"
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
