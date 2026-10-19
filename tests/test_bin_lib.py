"""_lib.sh, find-files.sh and the lint and fix scripts built on them."""

import sys
lazy import subprocess
lazy from collections.abc import Callable
lazy from pathlib import Path

import pytest

from tests.bin_project import FAIL_EXIT, USAGE_EXIT, make_tree
lazy from tests.bin_project import Project

# Runs a bash snippet with _lib.sh sourced; keywords add to the environment.
type Lib = Callable[..., subprocess.CompletedProcess[str]]

# Every merged .shellignore starts from these.
_SHELLIGNORE = ".*\nnode_modules\n"


@pytest.fixture
def lib(project: Project, bash: str) -> Lib:
    """Return a runner for bash snippets that source _lib.sh under set -eu."""
    project.install("common/_lib.sh")

    def run(snippet: str, **env: str) -> subprocess.CompletedProcess[str]:
        code = f"set -euo pipefail\n. bin/_lib.sh\n{snippet}\n"
        return project.run(bash, "-c", code, **env)

    return run


# ---------------------------------------------------------------------------
# _lib.sh
# ---------------------------------------------------------------------------


def test_need_passes_for_an_installed_tool(project: Project, lib: Lib) -> None:
    """A tool on PATH passes need silently."""
    project.fake("hadolint")

    result = lib("need hadolint && echo found")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "found\n"
    assert result.stderr == ""


def test_need_names_a_missing_tool_and_how_to_install_it(lib: Lib) -> None:
    """A missing tool fails need, so a caller can skip it, and says how to get it."""
    result = lib('need no-such-tool || echo "status $?"')

    assert result.returncode == 0, result.stderr
    assert result.stdout == "status 1\n"
    assert result.stderr == (
        "skipped: no-such-tool not installed (brew install no-such-tool)\n"
    )


def test_need_fails_a_missing_tool_in_ci(lib: Lib) -> None:
    """In CI a missing tool fails the script instead of being skipped."""
    result = lib('need no-such-tool || echo "status $?"', CI="true")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "ERROR: no-such-tool not installed. CI must install it: brew install"
        " no-such-tool, or add it to the Dockerfile's CI stage\n"
    )


def test_load_files_reads_nul_delimited_names(lib: Lib) -> None:
    """Spaces, newlines and leading dashes survive."""
    snippet = """load_files printf '%s\\0' 'a b' "$(printf 'c\\nd')" -e
printf '<%s>' "${files[@]}"
echo " ${#files[@]}"
"""
    result = lib(snippet)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "<a b><c\nd><-e> 3\n"


def test_load_files_reads_no_output_as_no_files(lib: Lib) -> None:
    """An empty list is still an array set -u lets a caller count."""
    result = lib('files=(stale)\nload_files true\necho "${#files[@]}"')

    assert result.returncode == 0, result.stderr
    assert result.stdout == "0\n"


def test_load_files_fails_with_the_commands_status(lib: Lib) -> None:
    """A failing finder fails the caller under set -e, files or not."""
    snippet = f"""load_files sh -c 'printf "a.sh\\0"; exit {FAIL_EXIT}'
echo unreachable"""
    result = lib(snippet)

    assert result.returncode == FAIL_EXIT
    assert "unreachable" not in result.stdout


def test_load_files_returns_the_status_and_no_files(lib: Lib) -> None:
    """Tested by a caller, the status and an empty list come back."""
    snippet = f"""load_files sh -c 'printf "a.sh\\0"; exit {FAIL_EXIT}' ||
  echo "status $? files ${{#files[@]}}"
"""
    result = lib(snippet)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"status {FAIL_EXIT} files 0\n"


@pytest.mark.parametrize("command", ["true", "false"])
def test_load_files_leaves_no_temp_file(
    tmp_path: Path,
    lib: Lib,
    command: str,
) -> None:
    """The temp file goes whether the command passes or fails."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()

    lib(f"load_files {command} || true", TMPDIR=str(tmpdir))

    assert list(tmpdir.iterdir()) == []


def test_die_and_warn(lib: Lib) -> None:
    """The warn helper carries on; die stops with status 1."""
    result = lib("warn careful\necho next\ndie broken\necho unreachable")

    assert result.returncode == 1
    assert result.stdout == "next\n"
    assert result.stderr == "WARNING: careful\nERROR: broken\n"


def test_is_darwin(lib: Lib) -> None:
    """is_darwin succeeds on macOS only."""
    result = lib("if is_darwin; then echo yes; else echo no; fi")

    assert result.stdout == ("yes\n" if sys.platform == "darwin" else "no\n")


# ---------------------------------------------------------------------------
# find-files.sh
# ---------------------------------------------------------------------------


@pytest.fixture
def finder(project: Project) -> Project:
    """Install find-files.sh with a project-style .shellignore."""
    project.install("common/find-files.sh")
    (project.root / ".shellignore").write_text(_SHELLIGNORE)
    return project


def _found(project: Project, *args: str) -> list[str]:
    result = project.script("find-files.sh", *args)
    assert result.returncode == 0, result.stderr
    return [path for path in result.stdout.split("\0") if path]


def test_find_files_finds_every_dockerfile(finder: Project) -> None:
    """Every Dockerfile, not just the first, and none under pruned dirs."""
    make_tree(
        finder.root,
        "Dockerfile",
        "ci/Dockerfile",
        "docker/base.Dockerfile",
        "Dockerfile.dev",
        "node_modules/pkg/Dockerfile",
        "pkg/node_modules/x/Dockerfile",
        ".venv/lib/Dockerfile",
    )

    found = _found(finder, "--", "-name", "*Dockerfile")

    assert found == ["./Dockerfile", "./ci/Dockerfile", "./docker/base.Dockerfile"]


def test_find_files_finds_django_templates(finder: Project) -> None:
    """Templates at any depth, and none under node_modules or dot-dirs."""
    make_tree(
        finder.root,
        "app/templates/app/page.html",
        "templates/base.html",
        "app/templates/app/notes.txt",
        "app/static/page.html",
        "node_modules/pkg/templates/x.html",
        ".venv/lib/site/templates/y.html",
    )

    found = _found(finder, "--", "-path", "*/templates/*", "-name", "*.html")

    assert found == ["./app/templates/app/page.html", "./templates/base.html"]


def test_find_files_without_predicates_lists_every_file(finder: Project) -> None:
    """No predicates means every regular file the ignore file leaves."""
    make_tree(finder.root, "a.txt", "b/c", ".hidden/d", "node_modules/e")

    assert _found(finder) == ["./a.txt", "./b/c", "./bin/find-files.sh"]


def test_find_files_reads_the_named_ignore_file(finder: Project) -> None:
    """-i replaces .shellignore."""
    make_tree(finder.root, "build/a.txt", ".hidden/b.txt", "c.txt")
    (finder.root / "my.ignore").write_text("build\nbin\nmy.ignore\n")

    found = _found(finder, "-i", "my.ignore", "--", "-name", "*.txt")

    assert found == ["./.hidden/b.txt", "./c.txt"]


def test_find_files_rejects_a_missing_ignore_file(finder: Project) -> None:
    """A named ignore file that is not there is an error, not no excludes."""
    result = finder.script("find-files.sh", "-i", "nope", "--", "-name", "*")

    assert result.returncode == USAGE_EXIT
    assert "nope" in result.stderr
    assert result.stdout == ""


def test_find_files_needs_the_double_dash(finder: Project) -> None:
    """Predicates without -- are bad options."""
    result = finder.script("find-files.sh", "-name", "*.sh")

    assert result.returncode == USAGE_EXIT
    assert "usage:" in result.stderr
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# docker, django and ci linting
# ---------------------------------------------------------------------------


@pytest.fixture
def docker(finder: Project) -> Project:
    """Build a docker project with Dockerfiles inside and outside pruned dirs."""
    finder.install("common/_lib.sh", "docker/fix-docker.sh", "docker/lint-docker.sh")
    make_tree(finder.root, "Dockerfile", "ci/Dockerfile", "node_modules/Dockerfile")
    return finder


_DOCKERFILES = ["./Dockerfile", "./ci/Dockerfile"]


def test_lint_docker_lints_every_dockerfile(docker: Project) -> None:
    """Both linters get every Dockerfile."""
    docker.fake("hadolint", "dockerfmt")

    result = docker.script("lint-docker.sh")

    assert result.returncode == 0, result.stderr
    assert docker.argvs() == [_DOCKERFILES, ["--check", *_DOCKERFILES]]


def test_lint_docker_skips_a_missing_tool_out_loud(docker: Project) -> None:
    """A missing hadolint is reported and dockerfmt still runs."""
    docker.fake("dockerfmt")

    result = docker.script("lint-docker.sh")

    assert result.returncode == 0, result.stderr
    assert "skipped: hadolint not installed" in result.stderr
    assert docker.argvs("dockerfmt") == [["--check", *_DOCKERFILES]]


def test_fix_docker_formats_every_dockerfile(docker: Project) -> None:
    """Every Dockerfile is formatted."""
    docker.fake("dockerfmt")

    result = docker.script("fix-docker.sh")

    assert result.returncode == 0, result.stderr
    assert docker.argvs() == [["--write", *_DOCKERFILES]]


@pytest.mark.parametrize("script", ["fix-docker.sh", "lint-docker.sh"])
def test_docker_scripts_without_dockerfiles_run_nothing(
    finder: Project, script: str
) -> None:
    """No Dockerfile, no tools, and no complaint about missing ones."""
    finder.install("common/_lib.sh", f"docker/{script}")
    finder.fake("hadolint", "dockerfmt")

    result = finder.script(script)

    assert result.returncode == 0, result.stderr
    assert finder.calls() == []


@pytest.mark.parametrize(
    ("script", "flag"), [("fix-django.sh", "--reformat"), ("lint-django.sh", "--lint")]
)
def test_django_scripts_get_every_template(
    finder: Project, script: str, flag: str
) -> None:
    """The templates go to djlint, and none from node_modules."""
    finder.install("common/_lib.sh", f"django/{script}")
    finder.fake("uv")
    make_tree(
        finder.root,
        "app/templates/app/a.html",
        "other/templates/b.html",
        "node_modules/pkg/templates/c.html",
    )

    result = finder.script(script)

    assert result.returncode == 0, result.stderr
    templates = ["./app/templates/app/a.html", "./other/templates/b.html"]
    assert finder.argvs() == [["run", "--group", "lint", "djlint", flag, *templates]]


@pytest.mark.parametrize("script", ["fix-django.sh", "lint-django.sh"])
def test_django_scripts_without_templates_run_nothing(
    finder: Project, script: str
) -> None:
    """No templates is a message and success."""
    finder.install("common/_lib.sh", f"django/{script}")
    finder.fake("uv")

    result = finder.script(script)

    assert result.returncode == 0, result.stderr
    assert "No django template files found" in result.stdout
    assert finder.calls() == []


@pytest.fixture
def ci(project: Project) -> Project:
    """Build a project with workflows and lint-ci.sh."""
    project.install("common/_lib.sh", "ci/lint-ci.sh")
    workflows = project.root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for name in ("ci.yml", "devenv-check.yml", "extra.yaml"):
        (workflows / name).write_text("on: push\n")
    return project


def test_lint_ci_runs_actionlint_on_the_named_workflows(ci: Project) -> None:
    """The workflows are named, so actionlint needs no .git to find them."""
    ci.fake("actionlint")

    result = ci.script("lint-ci.sh")

    assert result.returncode == 0, result.stderr
    assert ci.argvs("actionlint") == [
        [
            ".github/workflows/ci.yml",
            ".github/workflows/devenv-check.yml",
            ".github/workflows/extra.yaml",
        ]
    ]


def test_lint_ci_with_an_empty_workflows_dir_needs_nothing(project: Project) -> None:
    """An empty workflows directory is nothing to lint and nothing to report."""
    project.install("common/_lib.sh", "ci/lint-ci.sh")
    (project.root / ".github" / "workflows").mkdir(parents=True)

    result = project.script("lint-ci.sh")

    assert result.returncode == 0, result.stderr
    assert "skipped" not in result.stderr
    assert project.calls() == []


def test_lint_ci_skips_a_missing_actionlint_out_loud(ci: Project) -> None:
    """Without actionlint the skip is reported, on any platform."""
    result = ci.script("lint-ci.sh")

    assert result.returncode == 0, result.stderr
    assert "skipped: actionlint not installed" in result.stderr


def test_lint_ci_without_workflows_needs_nothing(project: Project) -> None:
    """No workflows, nothing to lint, nothing to report."""
    project.install("common/_lib.sh", "ci/lint-ci.sh")

    result = project.script("lint-ci.sh")

    assert result.returncode == 0, result.stderr
    assert "skipped" not in result.stderr
