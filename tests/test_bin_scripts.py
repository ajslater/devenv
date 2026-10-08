"""
The copy/*/bin scripts: _lib.sh, find-files.sh and the scripts built on them.

Each test copies the scripts it needs into a project's ./bin and runs them as
make does, by their #!/usr/bin/env bash, once per bash the bash fixture finds,
macOS's stock 3.2 among them. PATH holds only fake tools, that bash and the
system directories, so no real linter, uv or bun is ever run. The fakes log
their argv, working directory and a few environment variables.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    # Runs a bash snippet with _lib.sh sourced; keywords add to the environment.
    Lib = Callable[..., subprocess.CompletedProcess[str]]

_ROOT = Path(__file__).resolve().parent.parent
_COPY = _ROOT / "copy"
_SYSTEM_PATH = ("/usr/bin", "/bin")
_STRIPPED_ENV_PREFIXES = ("BASH_FUNC_", "FAKE_")
_STRIPPED_ENV_KEYS = frozenset(
    ("BASH_ENV", "CDPATH", "ENV", "PYTHONDEVMODE", "PYTHONPATH", "DEBUG")
)
_LOGGED_ENV = ("DEBUG", "PYTHONDEVMODE", "PYTHONPATH")
_USAGE_EXIT = 2
_FAIL_EXIT = 5
# Every merged .shellignore starts from these.
_SHELLIGNORE = ".*\nnode_modules\n"

# A fake prints FAKE_STDOUT, and exits FAKE_FAIL_STATUS when its argv holds
# any of the space-separated words in FAKE_FAIL.
_FAKE_TOOL = """#!{python}
import json, os, sys
from pathlib import Path

entry = {{
    "tool": Path(sys.argv[0]).name,
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": {{key: os.environ.get(key) for key in {logged_env!r}}},
}}
with Path(os.environ["FAKE_TOOL_LOG"]).open("a") as log:
    log.write(json.dumps(entry) + "\\n")
sys.stdin.read()
sys.stdout.write(os.environ.get("FAKE_STDOUT", ""))
if set(os.environ.get("FAKE_FAIL", "").split()) & set(sys.argv[1:]):
    sys.exit(int(os.environ["FAKE_FAIL_STATUS"]))
"""


def _write_fake(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FAKE_TOOL.format(python=sys.executable, logged_env=_LOGGED_ENV))
    path.chmod(0o755)


def _make_tree(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")


@dataclass
class Project:
    """A child project with copied scripts, fake tools and a call log."""

    root: Path
    fakebin: Path
    log: Path
    env: dict[str, str]

    def install(self, *scripts: str) -> None:
        """Copy feature/name scripts from copy/<feature>/bin into ./bin."""
        for script in scripts:
            feature, name = script.split("/")
            shutil.copy2(_COPY / feature / "bin" / name, self.root / "bin" / name)

    def fake(self, *tools: str) -> None:
        """Put fake tools on PATH."""
        for tool in tools:
            _write_fake(self.fakebin / tool)

    def run(self, *argv: str | Path, **env: str) -> subprocess.CompletedProcess[str]:
        """Run a command in the project root, with extra environment."""
        return subprocess.run(  # noqa: S603
            argv,
            cwd=self.root,
            env={**self.env, **env},
            stdin=subprocess.DEVNULL,
            check=False,
            capture_output=True,
            text=True,
        )

    def script(
        self, name: str, *args: str, **env: str
    ) -> subprocess.CompletedProcess[str]:
        """Run ./bin/<name> as make would."""
        return self.run(f"bin/{name}", *args, **env)

    def calls(self, tool: str | None = None) -> list[dict]:
        """Return the fake tool calls, oldest first, optionally of one tool."""
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [call for call in calls if tool in (None, call["tool"])]

    def argvs(self, tool: str | None = None) -> list[list[str]]:
        """Return the argv of each fake tool call."""
        return [call["argv"] for call in self.calls(tool)]


@pytest.fixture
def project(tmp_path: Path, bash: str) -> Project:
    """Build an empty project whose PATH holds no real tools."""
    root = tmp_path / "project"
    (root / "bin").mkdir(parents=True)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_STRIPPED_ENV_PREFIXES) and key not in _STRIPPED_ENV_KEYS
    }
    env["PATH"] = os.pathsep.join((str(fakebin), str(Path(bash).parent), *_SYSTEM_PATH))
    log = tmp_path / "calls.jsonl"
    env["FAKE_TOOL_LOG"] = str(log)
    return Project(root.resolve(), fakebin, log, env)


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
    snippet = f"""load_files sh -c 'printf "a.sh\\0"; exit {_FAIL_EXIT}'
echo unreachable"""
    result = lib(snippet)

    assert result.returncode == _FAIL_EXIT
    assert "unreachable" not in result.stdout


def test_load_files_returns_the_status_and_no_files(lib: Lib) -> None:
    """Tested by a caller, the status and an empty list come back."""
    snippet = f"""load_files sh -c 'printf "a.sh\\0"; exit {_FAIL_EXIT}' ||
  echo "status $? files ${{#files[@]}}"
"""
    result = lib(snippet)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"status {_FAIL_EXIT} files 0\n"


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
    _make_tree(
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
    _make_tree(
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
    _make_tree(finder.root, "a.txt", "b/c", ".hidden/d", "node_modules/e")

    assert _found(finder) == ["./a.txt", "./b/c", "./bin/find-files.sh"]


def test_find_files_reads_the_named_ignore_file(finder: Project) -> None:
    """-i replaces .shellignore."""
    _make_tree(finder.root, "build/a.txt", ".hidden/b.txt", "c.txt")
    (finder.root / "my.ignore").write_text("build\nbin\nmy.ignore\n")

    found = _found(finder, "-i", "my.ignore", "--", "-name", "*.txt")

    assert found == ["./.hidden/b.txt", "./c.txt"]


def test_find_files_rejects_a_missing_ignore_file(finder: Project) -> None:
    """A named ignore file that is not there is an error, not no excludes."""
    result = finder.script("find-files.sh", "-i", "nope", "--", "-name", "*")

    assert result.returncode == _USAGE_EXIT
    assert "nope" in result.stderr
    assert result.stdout == ""


def test_find_files_needs_the_double_dash(finder: Project) -> None:
    """Predicates without -- are bad options."""
    result = finder.script("find-files.sh", "-name", "*.sh")

    assert result.returncode == _USAGE_EXIT
    assert "usage:" in result.stderr
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# docker, django and ci linting
# ---------------------------------------------------------------------------


@pytest.fixture
def docker(finder: Project) -> Project:
    """Build a docker project with Dockerfiles inside and outside pruned dirs."""
    finder.install("common/_lib.sh", "docker/fix-docker.sh", "docker/lint-docker.sh")
    _make_tree(finder.root, "Dockerfile", "ci/Dockerfile", "node_modules/Dockerfile")
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
    _make_tree(
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
    (project.root / ".github" / "workflows").mkdir(parents=True)
    return project


def test_lint_ci_runs_actionlint(ci: Project) -> None:
    """Workflows are linted."""
    ci.fake("actionlint")

    result = ci.script("lint-ci.sh")

    assert result.returncode == 0, result.stderr
    assert ci.argvs("actionlint") == [[]]


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


# ---------------------------------------------------------------------------
# python
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [0, 1, _FAIL_EXIT])
def test_test_python_erases_coverage_and_keeps_pytests_status(
    project: Project, status: int
) -> None:
    """The coverage files go even when pytest fails, and its status is kept."""
    project.install("python/test-python.sh")
    project.fake("uv")

    result = project.script(
        "test-python.sh", "-k", "x", FAKE_FAIL="pytest", FAKE_FAIL_STATUS=str(status)
    )

    assert result.returncode == status
    assert project.argvs() == [
        ["run", "--group", "test", "pytest", "-k", "x"],
        ["run", "--group", "test", "coverage", "erase"],
    ]
    assert (project.root / "test-results").is_dir()


@pytest.mark.parametrize(
    ("args", "argv"),
    [
        (("pkg",), ["--query-only"]),
        (("pkg", "--do-it"), ["-u", "me", "--do-it", "-y"]),
    ],
)
def test_cleanup_pypi_alpha_uses_the_pinned_pypi_cleanup(
    project: Project, args: tuple[str, ...], argv: list[str]
) -> None:
    """The dev group's pinned pypi-cleanup runs: uv run, not uvx."""
    project.install("python/cleanup-pypi-alpha.sh")
    project.fake("uv", "uvx")

    result = project.script(
        "cleanup-pypi-alpha.sh",
        *args,
        PYPI_USERNAME="me",
        PYPI_CLEANUP_PASSWORD="test-password",  # noqa: S106
    )

    assert result.returncode == 0, result.stderr
    pattern = ["-p", "pkg", "-r", r".*a\d+$"]
    assert project.argvs() == [["run", "pypi-cleanup", *pattern, *argv]]


@pytest.mark.parametrize("mode", ["--doit", "do-it", "--dry-run"])
def test_cleanup_pypi_alpha_rejects_an_unknown_mode(
    project: Project, mode: str
) -> None:
    """A typo of --do-it must not pass for a successful query."""
    project.install("python/cleanup-pypi-alpha.sh")
    project.fake("uv", "uvx")

    result = project.script("cleanup-pypi-alpha.sh", "pkg", mode)

    assert result.returncode == _USAGE_EXIT
    assert "Usage:" in result.stderr
    assert project.calls() == []


@pytest.mark.parametrize(
    ("env", "devmode"),
    [({}, "1"), ({"DEBUG": "1"}, "1"), ({"DEBUG": "0"}, None), ({"DEBUG": ""}, None)],
)
def test_dev_module_runs_from_the_callers_directory(
    project: Project, env: dict[str, str], devmode: str | None
) -> None:
    """The root goes on PYTHONPATH; dev mode only when DEBUG is truthy."""
    project.install("python/dev-module.sh")
    project.fake("uv")

    result = project.script("dev-module.sh", "pkg/main.py", PYTHONPATH="/x", **env)

    assert result.returncode == 0, result.stderr
    (call,) = project.calls()
    assert call["argv"] == ["run", "python3", "pkg/main.py"]
    assert call["cwd"] == str(project.root)
    assert call["env"]["PYTHONPATH"] == f"{project.root}{os.pathsep}/x"
    assert call["env"]["PYTHONDEVMODE"] == devmode


def test_uml_writes_under_test_results_with_the_import_name(project: Project) -> None:
    """A hyphenated project name becomes the import name pyreverse wants."""
    project.install("python/uml.sh")
    project.fake("uv", "uvx")

    result = project.script("uml.sh", FAKE_STDOUT="my-pkg\n")

    assert result.returncode == 0, result.stderr
    out = "test-results/uml"
    pyreverse = ["--from", "pylint", "pyreverse", "--output", "png"]
    assert project.argvs("uvx") == [[*pyreverse, "--output-directory", out, "my_pkg"]]
    assert (project.root / out).is_dir()


# ---------------------------------------------------------------------------
# django
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("pythonpath", "expected"), [(None, "."), ("/x", ".:/x")])
def test_pm_keeps_the_callers_pythonpath(
    project: Project, pythonpath: str | None, expected: str
) -> None:
    """The pm script adds the root to PYTHONPATH rather than replacing it."""
    project.install("django/pm")
    project.fake("uv")
    env = {"PYTHONPATH": pythonpath} if pythonpath else {}

    result = project.script("pm", "check", **env)

    assert result.returncode == 0, result.stderr
    (call,) = project.calls()
    assert call["argv"] == ["run", "python3", "bin/manage.py", "check"]
    assert call["env"]["PYTHONPATH"] == expected


@pytest.fixture
def ambiguous_django(project: Project) -> Project:
    """Build a project with two settings packages, which discovery refuses."""
    project.install("django/manage.py")
    for package in ("one", "two"):
        _make_tree(project.root, f"{package}/__init__.py", f"{package}/settings.py")
    return project


def test_manage_discovers_settings_only_when_unset(ambiguous_django: Project) -> None:
    """With two settings modules, discovery fails without the variable."""
    result = ambiguous_django.run(sys.executable, "bin/manage.py", "check")

    assert result.returncode != 0
    assert "Found 2 django settings modules" in result.stderr


def test_manage_trusts_an_explicit_settings_module(ambiguous_django: Project) -> None:
    """An explicit DJANGO_SETTINGS_MODULE skips discovery altogether."""
    result = ambiguous_django.run(
        sys.executable, "bin/manage.py", "check", DJANGO_SETTINGS_MODULE="one.settings"
    )

    assert "Found 2 django settings modules" not in result.stderr


# ---------------------------------------------------------------------------
# docker helpers
# ---------------------------------------------------------------------------


def test_docker_compose_exit_needs_a_service(project: Project) -> None:
    """A missing service is a usage message, not an unbound variable."""
    project.install("docker/docker-compose-exit.sh")
    project.fake("docker")

    result = project.script("docker-compose-exit.sh")

    assert result.returncode != 0
    assert "usage: bin/docker-compose-exit.sh <service>" in result.stderr
    assert project.calls() == []


def test_docker_compose_exit_runs_the_service(project: Project) -> None:
    """The service's exit code is the compose run's."""
    project.install("docker/docker-compose-exit.sh")
    project.fake("docker")

    result = project.script("docker-compose-exit.sh", "ci")

    assert result.returncode == 0, result.stderr
    assert project.argvs() == [["compose", "up", "--exit-code-from", "ci", "ci"]]


def test_docker_tag_latest_needs_credentials(project: Project) -> None:
    """Unset credentials get the friendly error on stderr."""
    project.install("docker/docker-tag-latest.sh")
    project.fake("docker")

    result = project.script("docker-tag-latest.sh", "ghcr.io", "me/app", "1.0.0")

    assert result.returncode == 1
    assert "DOCKER_PASS and DOCKER_USER" in result.stderr
    assert "unbound" not in result.stderr
    assert project.calls() == []


@pytest.mark.parametrize("status", [0, 1])
def test_docker_tag_latest_reports_the_retag(project: Project, status: int) -> None:
    """A failing retag fails the script with a message on stderr."""
    project.install("docker/docker-tag-latest.sh")
    project.fake("docker")

    result = project.script(
        "docker-tag-latest.sh",
        "ghcr.io",
        "me/app",
        "1.0.0",
        DOCKER_USER="me",
        DOCKER_PASS="test-password",  # noqa: S106
        FAKE_FAIL="imagetools",
        FAKE_FAIL_STATUS=str(status),
    )

    assert result.returncode == status
    if status:
        assert "Failed to update tag." in result.stderr
    else:
        assert "Successfully updated latest" in result.stdout
    assert project.argvs()[-1] == [
        "buildx",
        "imagetools",
        "create",
        "--tag",
        "ghcr.io/me/app:latest",
        "ghcr.io/me/app:1.0.0",
    ]


def _load_hub_prune_stale(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = _COPY / "docker" / "bin" / "hub_prune_stale.py"
    spec = importlib.util.spec_from_file_location("hub_prune_stale", path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_hub_prune_stale_reports_a_network_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A requests failure is an error line and exit 1, not a traceback."""
    requests = pytest.importorskip("requests")
    hub_prune_stale = _load_hub_prune_stale(monkeypatch)

    def unreachable(*_args: object, **_kwargs: object) -> int:
        reason = "no route to hub"
        raise requests.ConnectionError(reason)

    monkeypatch.setattr(hub_prune_stale, "prune", unreachable)
    monkeypatch.setattr(sys, "argv", ["hub_prune_stale.py", "me/app"])

    with pytest.raises(SystemExit) as exc_info:
        hub_prune_stale.main()

    assert exc_info.value.code == 1
    assert "error: no route to hub" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# node and frontend
# ---------------------------------------------------------------------------


@pytest.fixture
def node(project: Project) -> Project:
    """Build a project with version-node.sh and a fake bun."""
    project.install("node/version-node.sh")
    project.fake("bun")
    return project


@pytest.mark.parametrize(
    ("args", "argv"),
    [
        ((), ["pm", "pkg", "get", "name", "version"]),
        (("1.2.3",), ["pm", "pkg", "set", "version=1.2.3"]),
    ],
)
@pytest.mark.parametrize("subdir", ["frontend", ""])
def test_version_node_uses_frontend_or_the_root(
    node: Project, subdir: str, args: tuple[str, ...], argv: list[str]
) -> None:
    """frontend/package.json when there is a frontend, else ./package.json."""
    _make_tree(node.root, "package.json")
    if subdir:
        _make_tree(node.root, f"{subdir}/package.json")

    result = node.script("version-node.sh", *args)

    assert result.returncode == 0, result.stderr
    (call,) = node.calls()
    assert call["argv"] == argv
    assert call["cwd"] == str(node.root / subdir)


def test_version_node_without_package_json_is_an_error(node: Project) -> None:
    """Nothing to version is an error, not a silent success."""
    result = node.script("version-node.sh")

    assert result.returncode == 1
    assert "no package.json" in result.stderr
    assert node.calls() == []


_ESLINT_D_PATTERN = "^eslint_d - |node_modules/eslint_d/"


def test_kill_eslint_d_stops_the_local_daemon(project: Project) -> None:
    """The project's own eslint_d stops it; bunx never fetches one."""
    project.install("node/kill-eslint_d.sh")
    project.fake("pkill", "bunx")
    _write_fake(project.root / "node_modules" / ".bin" / "eslint_d")
    _make_tree(project.root, ".eslintcache")

    # A wedged daemon that will not stop, and pkill finding nothing, both pass.
    result = project.script(
        "kill-eslint_d.sh", FAKE_FAIL="stop -f", FAKE_FAIL_STATUS="1"
    )

    assert result.returncode == 0, result.stderr
    assert [(call["tool"], call["argv"]) for call in project.calls()] == [
        ("eslint_d", ["stop"]),
        ("pkill", ["-f", _ESLINT_D_PATTERN]),
    ]
    assert not (project.root / ".eslintcache").exists()


def test_kill_eslint_d_without_a_local_eslint_d(project: Project) -> None:
    """With no local eslint_d only pkill runs."""
    project.install("node/kill-eslint_d.sh")
    project.fake("pkill", "bunx")

    result = project.script("kill-eslint_d.sh")

    assert result.returncode == 0, result.stderr
    assert [call["tool"] for call in project.calls()] == ["pkill"]


@pytest.mark.parametrize(
    ("command", "matches"),
    [
        ("eslint_d - devenv", True),
        ("eslint_d - /Users/me/Code/app", True),
        ("node /app/node_modules/eslint_d/bin/eslint_d.js start", True),
        ("bash bin/kill-eslint_d.sh", False),
        ("make kill-eslint_d", False),
        ("vim eslint_d.md", False),
    ],
)
def test_the_eslint_d_pattern_spares_its_callers(
    command: str, *, matches: bool
) -> None:
    """The pkill -f pattern must not match the script or make that runs it."""
    assert (re.search(_ESLINT_D_PATTERN, command) is not None) is matches


def test_prettier_nginx_uses_bunx(project: Project) -> None:
    """The nginx configs go through bunx prettier, like every other format."""
    project.install("frontend/prettier-nginx.sh")
    project.fake("bunx", "prettier")
    (project.root / "nginx" / "http.d").mkdir(parents=True)

    result = project.script("prettier-nginx.sh", "--check")

    assert result.returncode == 0, result.stderr
    assert [(call["tool"], call["argv"]) for call in project.calls()] == [
        ("bunx", ["prettier", "--parser", "nginx", "nginx/http.d/*.conf", "--check"])
    ]
