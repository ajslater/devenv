"""The docker and node helper scripts."""

import importlib.util
import re
import sys
from typing import TYPE_CHECKING

import pytest

from tests.bin_project import COPY, make_tree, write_fake

if TYPE_CHECKING:
    from types import ModuleType

    from tests.bin_project import Project


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
    path = COPY / "docker" / "bin" / "hub_prune_stale.py"
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
    make_tree(node.root, "package.json")
    if subdir:
        make_tree(node.root, f"{subdir}/package.json")

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
    write_fake(project.root / "node_modules" / ".bin" / "eslint_d")
    make_tree(project.root, ".eslintcache")

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
