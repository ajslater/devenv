"""
merge_dotfiles drops each ignore pattern that another pattern in the file covers.

Each ignore file has its own syntax. In a .gitignore, "foo" matches at any
depth, as "**/foo" does. In a .dockerignore, "foo" matches only at the context
root, and "**/foo" matches at any depth. bin/find-sh.sh reads a .shellignore
name at any depth, but has no "**/" form.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
# merge_dotfiles imports its sibling _devenv_common as a top-level module.
sys.path.insert(0, str(_ROOT / "scripts"))
merge_dotfiles = importlib.import_module("merge_dotfiles")


def _pruned(name: str, *lines: str) -> set[str]:
    return set(lines) - merge_dotfiles.prune_covered(name, lines)


@pytest.mark.parametrize("name", [".gitignore", ".prettierignore"])
@pytest.mark.parametrize(
    ("lines", "pruned"),
    [
        # A name matches files and dirs at any depth, so it covers the rest.
        (
            ("dist", "dist/", "/dist", "/dist/", "**/dist"),
            {"dist/", "/dist", "/dist/", "**/dist"},
        ),
        # A glob covers the plain names it matches.
        ((".*cache", ".mypy_cache/", ".eslintcache"), {".mypy_cache/", ".eslintcache"}),
        # A dir-only glob doesn't cover a name that may be a file.
        ((".*cache/", ".eslintcache"), set()),
        # A root-anchored pattern doesn't cover one at any depth.
        (("/dist", "dist/"), set()),
        # An inner slash anchors a pattern, as a leading one does.
        (("docs/_build", "/docs/_build/"), {"/docs/_build/"}),
        # Matching is case-sensitive.
        (("env/", "ENV/"), set()),
        # A glob doesn't cover another glob, even a narrower one.
        (("*.egg", "*.egg-info/"), set()),
    ],
)
def test_gitignore_syntax(name: str, lines: tuple[str, ...], pruned: set[str]) -> None:
    """Covered .gitignore lines go."""
    assert _pruned(name, *lines) == pruned


@pytest.mark.parametrize(
    ("lines", "pruned"),
    [
        # "**/" matches at any depth, the root included.
        (
            ("**/node_modules", "node_modules", "/node_modules/"),
            {"node_modules", "/node_modules/"},
        ),
        (
            ("**/.*cache", ".mypy_cache", "**/.ruff_cache"),
            {".mypy_cache", "**/.ruff_cache"},
        ),
        # Docker disregards leading and trailing slashes.
        (("foo", "/foo", "foo/", "./foo"), {"/foo", "foo/", "./foo"}),
        # A root-only pattern doesn't cover one at any depth.
        (("node_modules", "**/node_modules/x"), set()),
        (("*.py[co]", "**/*.py[co]"), {"*.py[co]"}),
    ],
)
def test_dockerignore_syntax(lines: tuple[str, ...], pruned: set[str]) -> None:
    """Covered .dockerignore lines go."""
    assert _pruned(".dockerignore", *lines) == pruned


@pytest.mark.parametrize(
    ("lines", "pruned"),
    [
        (
            ("node_modules", "./node_modules", "/node_modules", "node_modules/"),
            {"./node_modules", "/node_modules", "node_modules/"},
        ),
        (("vendor", "**/vendor"), set()),
        ((".*", ".github"), {".github"}),
    ],
)
def test_shellignore_syntax(lines: tuple[str, ...], pruned: set[str]) -> None:
    """Covered .shellignore lines go, read as bin/find-sh.sh reads them."""
    assert _pruned(".shellignore", *lines) == pruned


def test_negation_keeps_every_line() -> None:
    """A sorted file puts a "!" line out of place, so its file is left whole."""
    assert _pruned(".gitignore", "dist", "dist/", "!dist/keep") == set()


@pytest.mark.parametrize("name", [".gitignore", ".shellcheckrc"])
def test_comments_blanks_and_rc_files_stay(name: str) -> None:
    """Only ignore patterns are pruned."""
    assert _pruned(name, "", "# dist", "#dist") == set()
    if name.endswith("rc"):
        assert _pruned(name, "dist", "dist/") == set()


def test_merge_drops_lines_the_template_now_covers(tmp_path: Path) -> None:
    """A project's root-only .dockerignore lines go once "**/" ones arrive."""
    templates = tmp_path / "merge"
    (templates / "docker").mkdir(parents=True)
    (templates / "docker" / ".dockerignore").write_text("**/.*cache\n**/node_modules\n")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".dockerignore").write_text(".mypy_cache\nmine\nnode_modules\n")

    merge_dotfiles.merge_dotfiles(templates, project, ["docker"])

    assert (
        project / ".dockerignore"
    ).read_text() == "**/.*cache\n**/node_modules\nmine\n"


def test_templates_have_no_covered_line() -> None:
    """Each template dotfile is already as short as its merge would make it."""
    for template in sorted((_ROOT / "merge").glob("*/.*ignore")):
        lines = template.read_text().splitlines()
        assert _pruned(template.name, *lines) == set(), template
