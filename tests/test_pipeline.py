"""
The whole update pipeline, run twice on a scratch child project.

update-devenv is meant to be re-run at any time, so a second run must leave
every file exactly as the first left it. bun, bunx, git and pkill are stubbed
out: their effects are not under devenv's control, and the merges and copies
are. A real pkill would stop every eslint_d on the machine.
"""

import json
import os
import stat
import tomllib
lazy from pathlib import Path

import pytest
import update_devenv
from _devenv_common import FEATURES

_STUB = "#!/bin/sh\nexit 0\n"
FEATURE_SETS = {
    "node-only": ("node", "node_root"),
    "python-only": ("python",),
    "defaults": ("common", "node", "node_root", "python"),
    "no-python": ("common", "docker", "node", "node_root"),
    "no-node-root": ("common", "node"),
    "django-no-frontend": ("django", "python"),
    "all": tuple(FEATURES),
}
# A project that already has its own values in every merged file.
_EXISTING_PROJECT = {
    "pyproject.toml": """\
[project]
name = "demo"
description = "A demo, with commas, in prose"
version = "1.0.0"

[[project.authors]]
name = "Someone Else"
email = "someone@example.com"

[tool.pytest]
addopts = ["-ra", "--strict-markers", "--cov"]
""",
    "package.json": json.dumps(
        {
            "name": "demo",
            "scripts": {"lint": "tsc --noEmit && eslint_d --cache ."},
        },
        indent=2,
    )
    + "\n",
    "zensical.toml": (
        '# The demo\'s docs.\n[project]\nsite_name = "Demo"\nnav = ["index.md"]\n'
    ),
}


def _stub_tools(bin_dir: Path) -> None:
    bin_dir.mkdir()
    for tool in ("bun", "bunx", "git", "pkill"):
        stub = bin_dir / tool
        stub.write_text(_STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def _snapshot(project: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def _run_update(project: Path, features: tuple[str, ...], mp: pytest.MonkeyPatch):
    for feature in FEATURES:
        mp.delenv(f"DEVENV_{feature.upper()}", raising=False)
    for feature in features:
        mp.setenv(f"DEVENV_{feature.upper()}", "1")
    mp.chdir(project)
    update_devenv.main()


@pytest.fixture
def child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an empty child project dir with bun, bunx, git and pkill stubbed."""
    _stub_tools(tmp_path / "stubs")
    monkeypatch.setenv("PATH", f"{tmp_path / 'stubs'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("DEVENV_SRC", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.mark.parametrize("seed", ["empty", "existing"])
@pytest.mark.parametrize("features", FEATURE_SETS.values(), ids=FEATURE_SETS.keys())
def test_second_run_changes_nothing(
    child: Path,
    monkeypatch: pytest.MonkeyPatch,
    features: tuple[str, ...],
    seed: str,
) -> None:
    """Every file a first run writes is a fixed point of the next run."""
    if seed == "existing":
        for name, text in _EXISTING_PROJECT.items():
            (child / name).write_text(text)

    _run_update(child, features, monkeypatch)
    first = _snapshot(child)
    _run_update(child, features, monkeypatch)

    assert _snapshot(child) == first


def test_first_run_keeps_the_projects_own_values(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Merging adds devenv's values without rewriting the project's."""
    for name, text in _EXISTING_PROJECT.items():
        (child / name).write_text(text)

    _run_update(child, FEATURE_SETS["all"], monkeypatch)

    pyproject = tomllib.loads((child / "pyproject.toml").read_text())
    assert pyproject["project"]["description"] == "A demo, with commas, in prose"
    assert pyproject["project"]["authors"] == [
        {"name": "Someone Else", "email": "someone@example.com"}
    ]
    assert pyproject["tool"]["pytest"]["addopts"][:3] == [
        "-ra",
        "--strict-markers",
        "--cov",
    ]
    lint = json.loads((child / "package.json").read_text())["scripts"]["lint"]
    assert lint == (
        "tsc --noEmit && eslint_d --cache --ignore-pattern frontend/ ."
        " && prettier --check ."
    )
    assert (child / "zensical.toml").read_text().startswith("# The demo's docs.\n")


def test_project_zensical_toml_survives_two_runs(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The docs merge keeps the project's comment, site_name and nav."""
    (child / "zensical.toml").write_text(_EXISTING_PROJECT["zensical.toml"])

    for _ in range(2):
        _run_update(child, ("docs", "python"), monkeypatch)

    text = (child / "zensical.toml").read_text()
    assert text.startswith("# The demo's docs.\n[project]\n")
    project = tomllib.loads(text)["project"]
    assert project["site_name"] == "Demo"
    assert project["nav"] == ["index.md"]
    assert project["docs_dir"] == "docs"


@pytest.mark.parametrize(
    ("features", "stopped"), [(("common", "node"), True), (("python",), False)]
)
def test_update_stops_eslint_d_with_the_node_feature(
    child: Path,
    monkeypatch: pytest.MonkeyPatch,
    features: tuple[str, ...],
    *,
    stopped: bool,
) -> None:
    """A running eslint_d would keep linting with the config it loaded."""
    log = child.parent / "pkill.log"
    (child.parent / "stubs" / "pkill").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    (child / ".eslintcache").write_text("{}")

    _run_update(child, features, monkeypatch)

    assert log.is_file() == stopped
    assert (child / ".eslintcache").is_file() != stopped


# A cfg/docs.mk from before the feature .mk files exported DEVENV_<FEATURE>.
_FLAGLESS_DOCS_MK = """\
.PHONY: docs
## Build doc site
## @category Docs
docs:
\tuv run --only-group docs --no-dev mkdocs build --strict --site-dir docs/site

.PHONY: docs-server
## Run the docs server
## @category Docs
docs-server:
\tuv run --only-group docs --no-dev mkdocs serve --open --dirty
"""


def test_makefile_include_enables_a_feature_without_its_flag(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An included cfg/docs.mk too old to export DEVENV_DOCS still gets docs."""
    (child / "Makefile").write_text("include cfg/python.mk\ninclude cfg/docs.mk\n")
    (child / "cfg").mkdir()
    (child / "cfg" / "docs.mk").write_text(_FLAGLESS_DOCS_MK)

    _run_update(child, ("python",), monkeypatch)

    assert (child / "zensical.toml").is_file()
    assert (child / "cfg" / "docs.mk").read_text().startswith("DEVENV_DOCS := 1\n")
    assert "site/" in (child / ".gitignore").read_text().splitlines()


def test_no_features_fails_before_touching_the_project(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run outside make, it says how to run it instead of half-updating."""
    with pytest.raises(SystemExit, match="make update-devenv"):
        _run_update(child, (), monkeypatch)
    assert not any(child.iterdir())


def test_unmet_requirement_fails_before_touching_the_project(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gha_std without ci would ship a workflow that calls missing ones."""
    with pytest.raises(SystemExit, match="'gha_std' requires 'ci'"):
        _run_update(child, ("gha_std", "python"), monkeypatch)
    assert not any(child.iterdir())


def test_missing_bun_fails_before_touching_the_project(
    child: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node feature needs bun; say so first, not after files have changed."""
    monkeypatch.setenv("PATH", str(child.parent / "stubs" / "none"))
    with pytest.raises(SystemExit, match="bun"):
        _run_update(child, ("node", "node_root"), monkeypatch)
    assert not any(child.iterdir())
