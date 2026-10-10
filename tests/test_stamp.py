"""
The .devenv-version stamp and the `# since` markers in retirement lists.

A project stamped with devenv version S already had every retirement from S
or earlier applied, so update-devenv skips those and leaves alone a file the
project has since added under a retired name.
"""

import re
from pathlib import Path

import pytest
import update_devenv
from _devenv_common import (
    FEATURES,
    STAMP_FILE,
    devenv_version,
    parse_version,
    read_lines,
    read_stamp,
)

_ROOT = Path(__file__).resolve().parent.parent
_RETIREMENT_LISTS = (
    "remove_dotfile_lines.txt",
    "remove_files.txt",
    "remove_node_packages.txt",
)
_LIST = """\
# Files update-devenv deletes.
old.sh

# since 0.2.0
newer.sh
# since v0.10.0
newest.sh
"""


def test_read_lines_without_stamp_returns_everything(tmp_path: Path) -> None:
    """An unstamped project gets every retirement."""
    path = tmp_path / "list.txt"
    path.write_text(_LIST)

    assert read_lines(path) == ["old.sh", "newer.sh", "newest.sh"]


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ((0, 1, 0), ["newer.sh", "newest.sh"]),
        ((0, 2, 0), ["newest.sh"]),
        ((0, 9, 9), ["newest.sh"]),
        ((0, 10, 0), []),
    ],
)
def test_read_lines_skips_what_the_stamp_has(
    tmp_path: Path, stamp: tuple[int, ...], expected: list[str]
) -> None:
    """Entries retired in the stamp's version or earlier are left out."""
    path = tmp_path / "list.txt"
    path.write_text(_LIST)

    assert read_lines(path, stamp) == expected


@pytest.mark.parametrize("name", _RETIREMENT_LISTS)
def test_markers_ascend_and_are_released(name: str) -> None:
    """Markers ascend and none is newer than devenv itself."""
    current = parse_version(devenv_version(_ROOT) or "0")
    markers = [
        parse_version(match[1])
        for match in re.finditer(r"(?m)^# since v?(\S+)$", (_ROOT / name).read_text())
    ]

    assert markers == sorted(markers)
    assert all(marker <= current for marker in markers)


def test_news_has_the_current_version() -> None:
    """update-devenv prints NEWS since a stamp, so each version has a section."""
    version = devenv_version(_ROOT)

    assert f"\n## v{version}\n" in (_ROOT / "NEWS.md").read_text()


def _fake_devenv(root: Path) -> Path:
    src = root / "devenv"
    (src / "copy" / "python" / "bin").mkdir(parents=True)
    (src / "copy" / "python" / "bin" / "shipped.sh").write_text("#!/bin/sh\n")
    (src / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    (src / "remove_files.txt").write_text(
        "bin/legacy.sh\n# since 0.3.0\nbin/retired.sh\n"
    )
    (src / "NEWS.md").write_text(
        "# News\n\n## v0.3.0\n\n- Third\n\n## v0.2.0\n\n- Second\n"
    )
    return src


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a python-only project that a small fake devenv updates."""
    monkeypatch.setenv("DEVENV_SRC", str(_fake_devenv(tmp_path)))
    for feature in FEATURES:
        monkeypatch.delenv(f"DEVENV_{feature.upper()}", raising=False)
    monkeypatch.setenv("DEVENV_PYTHON", "1")
    path = tmp_path / "project"
    (path / "bin").mkdir(parents=True)
    for name in ("legacy.sh", "retired.sh"):
        (path / "bin" / name).write_text("mine\n")
    monkeypatch.chdir(path)
    return path


def test_unstamped_project_gets_every_retirement_and_a_stamp(project: Path) -> None:
    """The first stamped update applies everything and records the version."""
    update_devenv.main(update_deps=False)

    assert not (project / "bin" / "legacy.sh").exists()
    assert not (project / "bin" / "retired.sh").exists()
    assert read_stamp(project) == (0, 3, 0)


def test_stamped_project_keeps_files_retired_before_its_stamp(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A project stamped 0.2.0 keeps its bin/legacy.sh but gets 0.3.0's changes."""
    (project / STAMP_FILE).write_text("0.2.0\n")

    update_devenv.main(update_deps=False)

    assert (project / "bin" / "legacy.sh").read_text() == "mine\n"
    assert not (project / "bin" / "retired.sh").exists()
    out = capsys.readouterr().out
    assert "- Third" in out
    assert "- Second" not in out
    assert (project / STAMP_FILE).read_text() == "0.3.0\n"
