"""The python and django bin scripts."""

import os
import sys
from typing import TYPE_CHECKING

import pytest

from tests.bin_project import FAIL_EXIT, USAGE_EXIT, make_tree

if TYPE_CHECKING:
    from tests.bin_project import Project


# ---------------------------------------------------------------------------
# python
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [0, 1, FAIL_EXIT])
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

    assert result.returncode == USAGE_EXIT
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
        make_tree(project.root, f"{package}/__init__.py", f"{package}/settings.py")
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


@pytest.mark.parametrize(
    ("verdict", "message"),
    [
        ("no-app", "django.contrib.staticfiles is not installed. Nothing to collect."),
        ("no-root", "settings.STATIC_ROOT is unset. Nothing to collect."),
        (
            "no-files",
            "No static files found outside rest_framework. Nothing to collect.",
        ),
    ],
)
def test_collectstatic_skips_when_django_has_nothing_to_collect(
    project: Project, verdict: str, message: str
) -> None:
    """Without staticfiles, collectstatic is not a command, so ask django first."""
    project.install("django/collectstatic.sh", "django/pm")
    project.fake("uv")

    result = project.script("collectstatic.sh", FAKE_STDOUT=verdict)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{message}\n"
    (call,) = project.calls()
    assert call["argv"][:5] == [
        "run",
        "python3",
        "bin/manage.py",
        "shell",
        "--verbosity",
    ]


def test_collectstatic_collects_when_django_has_static_files(project: Project) -> None:
    """Django reporting files to collect runs the real command."""
    project.install("django/collectstatic.sh", "django/pm")
    project.fake("uv")

    result = project.script("collectstatic.sh", FAKE_STDOUT="collect")

    assert result.returncode == 0, result.stderr
    _ask, collect = project.argvs("uv")
    assert collect == [
        "run",
        "python3",
        "bin/manage.py",
        "collectstatic",
        "--clear",
        "--no-input",
        "--ignore",
        "rest_framework",
    ]


def test_collectstatic_fails_on_an_answer_it_does_not_know(project: Project) -> None:
    """An answer the script does not know is an error that quotes it, not a skip."""
    project.install("django/collectstatic.sh", "django/pm")
    project.fake("uv")

    result = project.script("collectstatic.sh", FAKE_STDOUT="Traceback")

    assert result.returncode == 1
    assert "Traceback" in result.stderr
    assert len(project.calls()) == 1
