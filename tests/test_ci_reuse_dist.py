"""
copy/ci/bin/ci-reuse-dist.sh against a fake gh.

The script finds the newest live ci-passed-<tree> marker artifact for HEAD's
tree and downloads that run's python-dist. A fake ``gh`` on PATH serves the
artifact listing from a JSON file and fakes ``gh run download``; git and jq
are real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "copy" / "ci" / "bin" / "ci-reuse-dist.sh"
_BASH = shutil.which("bash") or ""
_GIT = shutil.which("git") or ""
_JQ = shutil.which("jq") or ""

pytestmark = pytest.mark.skipif(
    not (_BASH and _GIT and _JQ), reason="needs bash, git and jq"
)

_REPO_ID = 100
_FORK_ID = 200
_THIS_RUN = 999
_WHEEL = "demo-1.0-py3-none-any.whl"
_STRIPPED_ENV_PREFIXES = ("GH_", "GIT_", "GITHUB_")
# A startup file named by these could reset PATH and hide the fake gh.
_STRIPPED_ENV_KEYS = frozenset(("BASH_ENV", "CDPATH", "ENV"))
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Reuse Test",
    "GIT_AUTHOR_EMAIL": "reuse@example.com",
    "GIT_COMMITTER_NAME": "Reuse Test",
    "GIT_COMMITTER_EMAIL": "reuse@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

_FAKE_GH = """#!{python}
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["FAKE_GH_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "api":
    listing = Path(os.environ["FAKE_GH_ARTIFACTS"])
    if not listing.exists():
        sys.stderr.write("HTTP 403: Resource not accessible by integration\\n")
        sys.exit(1)
    sys.stdout.write(listing.read_text())
elif args[:2] == ["run", "download"]:
    if os.environ.get("FAKE_GH_DOWNLOAD") != "ok":
        sys.stderr.write("no artifact matches any of the names or patterns\\n")
        sys.exit(1)
    dist = Path(args[args.index("--dir") + 1])
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "{wheel}").write_text("wheel")
else:
    sys.exit(2)
"""


def _base_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_STRIPPED_ENV_PREFIXES) and key not in _STRIPPED_ENV_KEYS
    }
    env.update(_GIT_ENV)
    return env


def _artifact(
    run_id: int,
    created_at: str,
    *,
    expired: bool = False,
    head_repository_id: int = _REPO_ID,
) -> dict:
    return {
        "expired": expired,
        "created_at": created_at,
        "workflow_run": {
            "id": run_id,
            "repository_id": _REPO_ID,
            "head_repository_id": head_repository_id,
        },
    }


@dataclass
class Reuse:
    """A one-commit repo, a fake gh and the files the script writes."""

    tmp: Path
    repo: Path
    tree: str

    def set_artifacts(self, *artifacts: dict) -> None:
        """Set the artifact listing the fake gh api returns."""
        listing = {"total_count": len(artifacts), "artifacts": list(artifacts)}
        self.set_listing(json.dumps(listing))

    def set_listing(self, text: str) -> None:
        """Set the raw text the fake gh api returns."""
        (self.tmp / "artifacts.json").write_text(text)

    def run(self, *, download: str = "ok") -> subprocess.CompletedProcess[str]:
        """Run the script in the repo."""
        env = _base_env()
        env.update(
            PATH=f"{self.tmp / 'fakebin'}{os.pathsep}{env.get('PATH', '')}",
            GH_REPO="owner/demo",
            GITHUB_OUTPUT=str(self.output_file),
            GITHUB_RUN_ID=str(_THIS_RUN),
            FAKE_GH_LOG=str(self.tmp / "gh-log.jsonl"),
            FAKE_GH_ARTIFACTS=str(self.tmp / "artifacts.json"),
            FAKE_GH_DOWNLOAD=download,
        )
        return subprocess.run(  # noqa: S603
            [_BASH, str(_SCRIPT)],
            cwd=self.repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    @property
    def output_file(self) -> Path:
        """Return the fake GITHUB_OUTPUT file."""
        return self.tmp / "github-output"

    def outputs(self) -> dict[str, str]:
        """Return what the script wrote to GITHUB_OUTPUT."""
        if not self.output_file.exists():
            return {}
        lines = self.output_file.read_text().splitlines()
        return dict(line.split("=", 1) for line in lines)

    def gh_calls(self) -> list[list[str]]:
        """Return every fake gh call's arguments, oldest first."""
        log = self.tmp / "gh-log.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def reuse(tmp_path: Path) -> Reuse:
    """Build a repo with one commit and a fake gh on PATH."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.txt").write_text("one\n")
    env = _base_env()
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "one")):
        subprocess.run([_GIT, *args], cwd=repo, env=env, check=True)  # noqa: S603
    tree = subprocess.run(  # noqa: S603
        [_GIT, "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    gh = fakebin / "gh"
    gh.write_text(_FAKE_GH.format(python=sys.executable, wheel=_WHEEL))
    gh.chmod(0o755)
    return Reuse(tmp_path, repo, tree)


def test_reuses_the_newest_passing_run(reuse: Reuse) -> None:
    """The newest live marker wins and its run's dist is downloaded."""
    reuse.set_artifacts(
        _artifact(1, "2026-09-01T00:00:00Z"),
        _artifact(3, "2026-09-03T00:00:00Z"),
        _artifact(2, "2026-09-02T00:00:00Z"),
    )

    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert reuse.outputs() == {"dist_found": "true", "source_run_id": "3"}
    assert (reuse.repo / "dist" / _WHEEL).exists()
    api, download = reuse.gh_calls()
    assert f"name=ci-passed-{reuse.tree}&" in api[1]
    assert download == [
        "run",
        "download",
        "3",
        "--name",
        "python-dist",
        "--dir",
        "dist",
    ]


@pytest.mark.parametrize(
    "artifact",
    [
        _artifact(5, "2026-09-05T00:00:00Z", expired=True),
        _artifact(5, "2026-09-05T00:00:00Z", head_repository_id=_FORK_ID),
        _artifact(_THIS_RUN, "2026-09-05T00:00:00Z"),
    ],
    ids=["expired", "fork", "this-run"],
)
def test_ineligible_markers_are_skipped(reuse: Reuse, artifact: dict) -> None:
    """Expired, fork and same-run markers never win over an older good one."""
    reuse.set_artifacts(_artifact(4, "2026-09-04T00:00:00Z"), artifact)

    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert reuse.outputs()["source_run_id"] == "4"


def test_only_ineligible_markers_is_a_miss(reuse: Reuse) -> None:
    """A fork's marker alone never supplies a dist."""
    reuse.set_artifacts(
        _artifact(5, "2026-09-05T00:00:00Z", head_repository_id=_FORK_ID)
    )

    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert len(reuse.gh_calls()) == 1


def test_no_marker_is_a_miss(reuse: Reuse) -> None:
    """No earlier passing run: continue with the full check."""
    reuse.set_artifacts()

    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert "No earlier run passed" in result.stdout


def test_download_failure_falls_through(reuse: Reuse) -> None:
    """A marker whose dist cannot be downloaded is not reuse."""
    reuse.set_artifacts(_artifact(4, "2026-09-04T00:00:00Z"))

    result = reuse.run(download="fail")

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert "Could not download python-dist from run 4" in result.stdout


def test_api_failure_falls_through(reuse: Reuse) -> None:
    """An artifacts API error warns and continues with the full check."""
    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert "::warning::Could not list artifacts" in result.stdout


def test_tree_failure_falls_through(reuse: Reuse) -> None:
    """A HEAD without a tree, as in a repo with no commits, never aborts the gate."""
    empty = reuse.tmp / "empty"
    empty.mkdir()
    subprocess.run([_GIT, "init", "-q"], cwd=empty, env=_base_env(), check=True)  # noqa: S603
    reuse.set_artifacts(_artifact(4, "2026-09-04T00:00:00Z"))

    result = replace(reuse, repo=empty).run()

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert not reuse.gh_calls()
    assert "::warning::Could not read the git tree of HEAD" in result.stdout


@pytest.mark.parametrize(
    "listing",
    ["<html>Service Unavailable</html>", '{"message": "Bad credentials"}'],
    ids=["not-json", "no-artifacts"],
)
def test_unreadable_listing_falls_through(reuse: Reuse, listing: str) -> None:
    """A listing jq cannot read warns and continues with the full check."""
    reuse.set_listing(listing)

    result = reuse.run()

    assert result.returncode == 0, result.stderr
    assert not reuse.outputs()
    assert len(reuse.gh_calls()) == 1
    assert "::warning::Could not read the artifact list" in result.stdout


def test_script_parses() -> None:
    """Check that bash -n accepts the script."""
    subprocess.run([_BASH, "-n", str(_SCRIPT)], check=True)  # noqa: S603


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="needs shellcheck")
def test_script_passes_shellcheck() -> None:
    """Shellcheck is clean."""
    shellcheck = shutil.which("shellcheck") or ""
    subprocess.run([shellcheck, str(_SCRIPT)], check=True)  # noqa: S603
