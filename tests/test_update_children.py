"""
update_children.py against scratch projects beside a scratch devenv.

Each project is a git repo whose cfg/common.mk logs the targets real make runs,
so nothing installs or formats anything.
"""

import os
import shutil
import subprocess
lazy from pathlib import Path

import pytest
import update_children

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Children Test",
    "GIT_AUTHOR_EMAIL": "children@example.com",
    "GIT_COMMITTER_NAME": "Children Test",
    "GIT_COMMITTER_EMAIL": "children@example.com",
    # Keep the developer's own git config (signing, hooks, aliases) out.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
# Each target logs the project, the target and what make was handed.
_LOGGED = (
    '@echo "$(notdir $(CURDIR)) $@ src=$(DEVENV_SRC) venv=$(VIRTUAL_ENV)'
    ' flags=$(UPDATE_DEVENV_FLAGS)" >> "$(LOG)"'
)
_UPDATE_DEVENV = f"update-devenv:\n\t{_LOGGED}\n\t@echo 0.4.6 > .devenv-version\n"

pytestmark = pytest.mark.skipif(
    not (shutil.which("git") and shutil.which("make")), reason="needs git and make"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a code dir holding a devenv that is not a git checkout."""
    code = tmp_path / "code"
    (code / "devenv" / "scripts").mkdir(parents=True)
    (code / "devenv" / "scripts" / "update_devenv.py").touch()
    (code / "devenv" / "Makefile").write_text("include cfg/common.mk\n")
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, value in _GIT_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DEVENV_SRC", str(code / "devenv"))
    monkeypatch.setenv("LOG", str(tmp_path / "make.log"))
    return code


def _project(code: Path, name: str, *targets: str, recipe: str = _LOGGED) -> Path:
    """Commit a project whose make has update-devenv and the given targets."""
    path = code / name
    (path / "cfg").mkdir(parents=True)
    # As in the starter Makefile, whose := beats the environment's DEVENV_SRC.
    (path / "Makefile").write_text(
        "DEVENV_SRC := ../devenv\ninclude cfg/python.mk\ninclude cfg/common.mk\n"
    )
    (path / "cfg" / "python.mk").write_text("")
    rules = "".join(f"{target}:\n\t{recipe}\n" for target in targets)
    (path / "cfg" / "common.mk").write_text(_UPDATE_DEVENV + rules)
    _git(path, "init", "-q", "-b", "develop")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "first")
    return path


def _log(code: Path) -> list[str]:
    log = code.parent / "make.log"
    return log.read_text().splitlines() if log.is_file() else []


def test_find_projects(code: Path) -> None:
    """Only directories whose Makefile includes cfg/common.mk are projects."""
    _project(code, "b")
    _project(code, "a")
    (code / "commented").mkdir()
    (code / "commented" / "Makefile").write_text("# include cfg/common.mk\n")
    (code / "plain").mkdir()
    (code / "plain" / "Makefile").write_text("all:\n")
    (code / "empty").mkdir()
    (code / "notes.txt").write_text("include cfg/common.mk\n")

    assert update_children.find_projects(code) == [code / "a", code / "b"]


def test_main_checkout_from_a_worktree(tmp_path: Path, code: Path) -> None:
    """A worktree inside the main checkout still finds the main checkout."""
    devenv = code / "devenv"
    _git(devenv, "init", "-q", "-b", "main")
    _git(devenv, "commit", "-q", "--allow-empty", "-m", "first")
    worktree = devenv / ".claude" / "worktrees" / "feature"
    _git(devenv, "worktree", "add", "-q", "-b", "feature", str(worktree))

    assert update_children.main_checkout(worktree) == devenv.resolve()
    assert update_children.main_checkout(devenv) == devenv.resolve()
    assert update_children.main_checkout(tmp_path) == tmp_path


def test_list_file_limits_the_projects(
    code: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only listed projects run; a listed name that is no project is reported."""
    for name in ("a", "b", "c"):
        _project(code, name)
    list_file = code / "devenv" / update_children.LIST_FILE
    list_file.write_text("# mine\nc\n\na/\nnope\nc\n")

    assert update_children.main([]) == 0

    assert [line.split()[0] for line in _log(code)] == ["a", "c"]
    out, err = capsys.readouterr()
    assert f"2 projects in {code} listed in {list_file}" in out
    assert err == f"{list_file} lists what are not devenv projects in {code}: nope\n"


def test_list_file_bounds_named_projects(code: Path) -> None:
    """A project left off the list cannot be named on the command line."""
    _project(code, "a")
    _project(code, "b")
    (code / "devenv" / update_children.LIST_FILE).write_text("a\n")

    with pytest.raises(SystemExit, match=r"not devenv projects in .* listed in .*: b"):
        update_children.main(["b"])
    assert not _log(code)


def test_list_file_is_read_from_the_main_checkout(
    code: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree has no copy of the ignored list file, so the main one counts."""
    devenv = code / "devenv"
    _git(devenv, "init", "-q", "-b", "main")
    _git(devenv, "commit", "-q", "--allow-empty", "-m", "first")
    worktree = devenv / ".claude" / "worktrees" / "feature"
    _git(devenv, "worktree", "add", "-q", "-b", "feature", str(worktree))
    (devenv / update_children.LIST_FILE).write_text("b\n")
    _project(code, "a")
    _project(code, "b")
    monkeypatch.setenv("DEVENV_SRC", str(worktree))

    assert update_children.main([]) == 0

    assert [line.split()[:3] for line in _log(code)] == [
        ["b", "update-devenv", f"src={worktree.resolve()}"]
    ]


def test_runs_each_step_in_order(
    code: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """update-devenv, update and fix run in turn; a missing target is skipped."""
    _project(code, "a", "update", "fix")
    _project(code, "b", "fix")
    monkeypatch.setenv("VIRTUAL_ENV", "/uv/script/env")

    assert update_children.main(["--update", "--fix"]) == 0

    src = code / "devenv"
    assert _log(code) == [
        f"a update-devenv src={src} venv= flags=",
        f"a update src={src} venv= flags=",
        f"a fix src={src} venv= flags=",
        f"b update-devenv src={src} venv= flags=",
        f"b fix src={src} venv= flags=",
    ]
    summary = capsys.readouterr().out.split("Summary:")[1].splitlines()[1:]
    assert [line.split() for line in summary] == [
        ["ok", "a", "develop", "1", "uncommitted", "files"],
        ["ok", "b", "develop", "no", "update", "target;", "1", "uncommitted", "files"],
    ]


def test_leaves_devenv_flags_out(code: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A DEVENV_<FEATURE> in the caller's environment never reaches a project."""
    _project(code, "a", "fix", recipe='@echo "docs=$(DEVENV_DOCS)" >> "$(LOG)"')
    monkeypatch.setenv("DEVENV_DOCS", "1")

    update_children.main(["--fix"])

    assert _log(code)[-1] == "docs="


def test_skips_uncommitted_work_unless_dirty(
    code: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A project with changes is left alone, and --dirty includes it."""
    _project(code, "a")
    (_project(code, "b") / "wip.py").write_text("")

    assert update_children.main([]) == 0
    assert [line.split()[0] for line in _log(code)] == ["a"]
    assert "skipped  b  develop  1 uncommitted files" in capsys.readouterr().out

    assert update_children.main(["--dirty", "b"]) == 0
    assert [line.split()[0] for line in _log(code)] == ["a", "b"]


def test_a_failure_stops_only_that_project(
    code: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed step skips the project's later steps, and the run goes on."""
    _project(code, "a", "update", recipe="@exit 1")
    _project(code, "b", "update")

    assert update_children.main(["--update"]) == 1

    assert [" ".join(line.split()[:2]) for line in _log(code)] == [
        "a update-devenv",
        "b update-devenv",
        "b update",
    ]
    assert "failed  a  develop  make update failed" in capsys.readouterr().out


def test_no_update_deps_reaches_update_devenv_only(code: Path) -> None:
    """--no-update-deps is handed to update-devenv, not to the later steps."""
    _project(code, "a", "fix")

    update_children.main(["--no-update-deps", "--fix"])

    assert [line.split()[1] + " " + line.split()[-1] for line in _log(code)] == [
        "update-devenv flags=--no-update-deps",
        "fix flags=",
    ]


def test_dry_run_runs_nothing(code: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--dry-run lists each project and its missing targets."""
    _project(code, "a", "fix")

    assert update_children.main(["-n", "--update", "--fix"]) == 0

    assert not _log(code)
    assert "would run  a  develop  no update target" in capsys.readouterr().out


def test_unknown_project_names_exit(code: Path) -> None:
    """A name that is not a project beside devenv is an error, not a no-op."""
    _project(code, "a")

    with pytest.raises(SystemExit, match=r"not devenv projects in .*: nope"):
        update_children.main(["a", "nope"])
    assert not _log(code)
