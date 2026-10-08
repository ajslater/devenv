"""copy/django/cfg/django.mk run by make, with and without frontend.mk."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_COPY = Path(__file__).resolve().parent.parent / "copy"
_MAKE = shutil.which("make")


@pytest.mark.skipif(not _MAKE, reason="needs make")
@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (("django",), ["collectstatic"]),
        (("django", "frontend"), ["build-frontend", "collectstatic"]),
    ],
)
def test_collectstatic_builds_a_frontend_only_when_there_is_one(
    tmp_path: Path, features: tuple[str, ...], expected: list[str]
) -> None:
    """Collectstatic needs no frontend, and builds one first when included."""
    assert _MAKE
    for feature in features:
        shutil.copy(_COPY / feature / "cfg" / f"{feature}.mk", tmp_path)
    (tmp_path / "Makefile").write_text(
        "".join(f"include {feature}.mk\n" for feature in features)
    )
    script = tmp_path / "bin" / "collectstatic.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho collectstatic\n")
    script.chmod(0o755)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "Makefile").write_text("build:\n\t@echo build-frontend\n")

    result = subprocess.run(  # noqa: S603
        [_MAKE, "-s", "--no-print-directory", "collectstatic"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.split() == expected
    assert not result.stderr
