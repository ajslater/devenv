"""Shared fixtures for the tests that run bin/ shell scripts."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.bin_project import Project

_SYSTEM_PATH = ("/usr/bin", "/bin")
_STRIPPED_ENV_PREFIXES = ("BASH_FUNC_", "FAKE_")
_STRIPPED_ENV_KEYS = frozenset(
    ("BASH_ENV", "CDPATH", "ENV", "PYTHONDEVMODE", "PYTHONPATH", "DEBUG")
)


def _bash_params() -> list:
    """
    Return each distinct bash to test under, named by its version.

    The bin/ scripts must run under macOS's stock /bin/bash, which is 3.2, as
    well as under whatever newer bash is first on PATH.
    """
    paths = dict.fromkeys(
        str(Path(path).resolve())
        for path in (shutil.which("bash"), "/bin/bash")
        if path and Path(path).is_file()
    )
    params = []
    for path in paths:
        version = subprocess.run(  # noqa: S603
            [path, "-c", 'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        params.append(pytest.param(path, id=f"bash-{version}"))
    return params or [pytest.param("", id="no-bash")]


@pytest.fixture(params=_bash_params())
def bash(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """
    Put each bash first on PATH and return the path to run it by.

    Scripts start with #!/usr/bin/env bash, so the scripts a script runs get
    the same bash only when it comes first on PATH.
    """
    if not request.param:
        pytest.skip("needs bash")
    shim = tmp_path_factory.mktemp("bash")
    (shim / "bash").symlink_to(request.param)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ.get('PATH', '')}")
    return str(shim / "bash")


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
