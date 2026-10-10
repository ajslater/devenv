"""add_features: feature resolution, Makefile includes and starter files."""

from pathlib import Path

import add_features
import pytest
from _makefiles import include_features, included_features

_ROOT = Path(__file__).resolve().parent.parent
_INIT_MAKEFILE = (_ROOT / "init" / "common" / "Makefile").read_text()


def _includes(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("include ")]


def test_include_uncomments_in_place() -> None:
    """The starter's commented includes are switched on where they stand."""
    text = include_features(_INIT_MAKEFILE, ["docs", "ci", "python"])

    assert _includes(text) == [
        "include cfg/python.mk",
        "include cfg/ci.mk",
        "include cfg/docs.mk",
        "include cfg/node.mk",
        "include cfg/node_root.mk",
        "include cfg/common.mk",
        "include cfg/help.mk",
    ]


def test_include_inserts_missing_lines_in_order() -> None:
    """A Makefile without a feature's line gets it between its neighbours."""
    makefile = "include cfg/codex.mk\ninclude cfg/python.mk\ninclude cfg/common.mk\n"

    text = include_features(makefile, ["django", "docs", "common"])

    assert _includes(text) == [
        "include cfg/codex.mk",
        "include cfg/django.mk",
        "include cfg/python.mk",
        "include cfg/docs.mk",
        "include cfg/common.mk",
        "include cfg/help.mk",
    ]


def test_include_is_idempotent() -> None:
    """Running it on its own output changes nothing."""
    once = include_features(_INIT_MAKEFILE, ["docker", "gha_std", "ci"])

    assert include_features(once, ["docker", "gha_std", "ci"]) == once


def test_include_never_removes_or_reorders() -> None:
    """Project order that differs from the canonical one is kept."""
    makefile = "include cfg/docker.mk\ninclude cfg/ci.mk\n"

    assert include_features(makefile, ["ci", "docker"]) == makefile


def test_included_features_ignores_comments(tmp_path: Path) -> None:
    """Only live includes count as enabled."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(_INIT_MAKEFILE)

    assert included_features(makefile) == ["python", "node", "node_root", "common"]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return an empty project dir that is the current directory."""
    monkeypatch.delenv("DEVENV_SRC", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_unmet_requirement_exits_before_copying(project: Path) -> None:
    """Django without python fails with one line naming the gap."""
    with pytest.raises(SystemExit, match="'django' requires 'python'"):
        add_features.add_features(["django"], init=False, convert=False)
    assert not any(project.iterdir())


def test_unknown_feature_exits(project: Path) -> None:
    """A typo is an error, not a silently ignored flag."""
    with pytest.raises(SystemExit, match="unknown feature 'rust'"):
        add_features.add_features(["rust"], init=True, convert=False)
    assert not any(project.iterdir())


def test_init_adds_defaults_and_requested(project: Path) -> None:
    """`init-project.sh docs ci` ends with both included, plus the defaults."""
    features = add_features.add_features(["docs", "ci"], init=True, convert=False)

    assert features == ["python", "ci", "docs", "node", "node_root", "common"]
    assert included_features(project / "Makefile") == features
    assert (project / "cfg" / "docs.mk").is_file()
    assert (project / "eslint.config.js").is_file()
    assert not (project / "eslint.config.init.js").exists()


def test_init_keeps_existing_files(project: Path) -> None:
    """Starters never replace what the project already has."""
    (project / "README.md").write_text("# Mine\n")
    (project / "pyproject.toml").write_text('[project]\nname = "mine"\n')

    add_features.add_features([], init=True, convert=False)

    assert (project / "README.md").read_text() == "# Mine\n"
    assert (project / "pyproject.toml").read_text() == '[project]\nname = "mine"\n'


def test_add_keeps_what_the_makefile_includes(project: Path) -> None:
    """Adding docker to a project keeps its existing features."""
    add_features.add_features([], init=True, convert=False)

    features = add_features.add_features(["docker"], init=False, convert=False)

    assert features == ["python", "docker", "node", "node_root", "common"]
    assert included_features(project / "Makefile") == features


def test_convert_keeps_old_files_once(project: Path) -> None:
    """The old Makefile survives as a reference, and a rerun keeps it."""
    (project / "Makefile").write_text("old:\n\techo old\n")
    (project / "eslint.config.js").write_text("export default [];\n")

    add_features.add_features([], init=False, convert=True)
    add_features.add_features([], init=False, convert=True)

    assert (project / "Makefile.orig.mk").read_text() == "old:\n\techo old\n"
    assert (project / "eslint.config.orig.js").read_text() == "export default [];\n"
    assert "include cfg/common.mk" in (project / "Makefile").read_text()
