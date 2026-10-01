"""
copy/common/bin/find-sh.sh and the fix-sh.sh / lint-sh.sh scripts built on it.

find-sh.sh prints the shell scripts under the current directory, NUL-delimited
and sorted, minus whatever ./.shellignore excludes. The finder tests run it
against ``tmp_path`` trees. The fix and lint tests put fake shellcheck,
shellharden and shfmt on PATH that only log their argv, so they show exactly
which files each tool is handed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BIN = _ROOT / "copy" / "common" / "bin"
_FIND_SH = _BIN / "find-sh.sh"
_BASH = shutil.which("bash") or ""

_SCRIPT_NAMES = ("find-sh.sh", "fix-sh.sh", "lint-sh.sh")
# The exit status of a stub finder that fails after printing a file.
_FINDER_EXIT = 3
_STRIPPED_ENV_PREFIXES = ("BASH_FUNC_", "FAKE_")
# A startup file named by these could reset PATH and hide the fake tools.
_STRIPPED_ENV_KEYS = frozenset(("BASH_ENV", "CDPATH", "ENV", "LC_ALL"))

_FAKE_TOOL = """#!{python}
import json, os, sys
from pathlib import Path

entry = {{"tool": Path(sys.argv[0]).name, "argv": sys.argv[1:]}}
with Path(os.environ["FAKE_TOOL_LOG"]).open("a") as log:
    log.write(json.dumps(entry) + "\\n")
"""

_SHFMT_FLAGS = ["--simplify", "--indent", "2"]
# What each script runs, in order: (tool, flags before the file list).
_TOOL_RUNS = {
    "fix-sh.sh": [
        ("shellharden", ["--replace"]),
        ("shfmt", [*_SHFMT_FLAGS, "--write"]),
    ],
    "lint-sh.sh": [
        ("shellcheck", ["--external-sources"]),
        ("shellharden", ["--check"]),
        ("shfmt", [*_SHFMT_FLAGS, "--diff"]),
    ],
}


def _bash_has_mapfile_delimiter() -> bool:
    """Return True when bash can run ``mapfile -d`` (bash 4.4 and later)."""
    if not _BASH:
        return False
    result = subprocess.run(  # noqa: S603
        [_BASH, "-c", "mapfile -d '' _ </dev/null"],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


pytestmark = pytest.mark.skipif(not _BASH, reason="needs bash")
needs_mapfile = pytest.mark.skipif(
    not _bash_has_mapfile_delimiter(), reason="needs bash 4.4+ for mapfile -d"
)


def _base_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_STRIPPED_ENV_PREFIXES) and key not in _STRIPPED_ENV_KEYS
    }


def _touch(root: Path, *names: str) -> None:
    """Create each named file, and its parent directories, under root."""
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env bash\n")


def _dot(*names: str) -> list[str]:
    """Return names as find-sh.sh prints them, in its sorted order."""
    return sorted(f"./{name}" for name in names)


def _find(cwd: Path) -> list[str]:
    """Run find-sh.sh in cwd and return the NUL-delimited paths it printed."""
    result = subprocess.run(  # noqa: S603
        [_BASH, str(_FIND_SH)],
        cwd=cwd,
        env=_base_env(),
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert result.stdout == b"" or result.stdout.endswith(b"\0")
    return [path.decode() for path in result.stdout.split(b"\0")[:-1]]


def _found(
    root: Path, files: list[str], ignore: str | bytes | None = None
) -> list[str]:
    """Build a tree, optionally with a .shellignore, and return what is found."""
    _touch(root, *files)
    if ignore is not None:
        data = ignore.encode() if isinstance(ignore, str) else ignore
        (root / ".shellignore").write_bytes(data)
    return _find(root)


# ---------------------------------------------------------------------------
# find-sh.sh
# ---------------------------------------------------------------------------


def test_no_shellignore_finds_every_sh_file(tmp_path: Path) -> None:
    """Without a .shellignore, every regular *.sh is found, hidden ones too."""
    files = ["top.sh", "a/b/deep.sh", ".hidden/x.sh", ".dot.sh", "a-b.sh"]
    _touch(tmp_path, *files, "notes.txt", "a/readme.md", "script.sh.bak", "shx")
    # Neither a directory nor a symlink named *.sh is a regular file.
    (tmp_path / "dir.sh").mkdir()
    (tmp_path / "dir.sh" / "inner.txt").write_text("x")
    (tmp_path / "link.sh").symlink_to(tmp_path / "top.sh")

    found = _find(tmp_path)

    assert found == _dot(*files)
    assert all(path.startswith("./") for path in found)


def test_output_is_sorted_bytewise(tmp_path: Path) -> None:
    """Sorting is LC_ALL=C: upper before lower, '-' and '.' before '/'."""
    files = ["a/x.sh", "a.sh", "a-b.sh", "a_b.sh", "B.sh", "Z/y.sh", "z.sh"]

    found = _found(tmp_path, files)

    assert found == [
        "./B.sh",
        "./Z/y.sh",
        "./a-b.sh",
        "./a.sh",
        "./a/x.sh",
        "./a_b.sh",
        "./z.sh",
    ]


def test_output_is_independent_of_the_callers_locale(tmp_path: Path) -> None:
    """A locale that would reorder the output must not change it."""
    _touch(tmp_path, "a.sh", "B.sh", "a-b.sh")
    env = _base_env()
    env["LC_ALL"] = "en_US.UTF-8"

    result = subprocess.run(  # noqa: S603
        [_BASH, str(_FIND_SH)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
    )

    assert result.stdout == b"./B.sh\0./a-b.sh\0./a.sh\0"


def test_odd_file_names_survive(tmp_path: Path) -> None:
    """NUL delimiting keeps spaces and newlines in names intact."""
    files = ["my script.sh", "two\nlines.sh", "-dash.sh"]

    assert _found(tmp_path, files) == _dot(*files)


def test_empty_tree_prints_nothing(tmp_path: Path) -> None:
    """No shell scripts is empty output and a zero exit, not an error."""
    _touch(tmp_path, "notes.txt")
    assert _find(tmp_path) == []


def test_basename_pattern_is_pruned_at_any_depth(tmp_path: Path) -> None:
    """A pattern without a slash matches a directory name at every depth."""
    files = [
        "node_modules/a.sh",
        "pkg/node_modules/b.sh",
        "pkg/deep/node_modules/x/y/c.sh",
        "keep.sh",
        "pkg/keep.sh",
        "node_modules_not/d.sh",
    ]

    found = _found(tmp_path, files, "node_modules\n")

    assert found == _dot("keep.sh", "pkg/keep.sh", "node_modules_not/d.sh")


def test_basename_pattern_skips_files_at_any_depth(tmp_path: Path) -> None:
    """A pattern without a slash also skips files of that name."""
    files = ["vendored.sh", "a/vendored.sh", "a/b/vendored.sh", "a/other.sh"]

    assert _found(tmp_path, files, "vendored.sh\n") == _dot("a/other.sh")


def test_anchored_pattern_matches_only_from_the_root(tmp_path: Path) -> None:
    """A pattern with a slash is anchored: a/b is not other/a/b."""
    files = ["a/b/x.sh", "other/a/b/y.sh", "a/b2/z.sh", "a/c.sh", "b/w.sh"]

    found = _found(tmp_path, files, "a/b\n")

    assert found == _dot("other/a/b/y.sh", "a/b2/z.sh", "a/c.sh", "b/w.sh")


def test_file_glob(tmp_path: Path) -> None:
    """A glob in an anchored pattern selects files."""
    files = ["scripts/x_old.sh", "scripts/new.sh", "other/x_old.sh", "top_old.sh"]

    found = _found(tmp_path, files, "scripts/*_old.sh\n")

    assert found == _dot("scripts/new.sh", "other/x_old.sh", "top_old.sh")


def test_anchored_star_crosses_directories(tmp_path: Path) -> None:
    """Find's -path lets * match /, so scripts/*_old.sh reaches subdirectories."""
    files = ["scripts/sub/deep/x_old.sh", "scripts/ok.sh"]

    assert _found(tmp_path, files, "scripts/*_old.sh\n") == _dot("scripts/ok.sh")


def test_question_mark_and_bracket_globs(tmp_path: Path) -> None:
    """? and [...] are passed through to find."""
    files = ["gen1/a.sh", "gen2/b.sh", "genx/c.sh", "v1/d.sh", "v22/e.sh"]

    found = _found(tmp_path, files, "gen[0-9]\nv?\n")

    assert found == _dot("genx/c.sh", "v22/e.sh")


def test_hidden_pattern_and_negation(tmp_path: Path) -> None:
    """.* then !.github keeps ./.github and drops other hidden paths."""
    files = [
        ".github/scripts/x.sh",
        ".github/workflows/w.sh",
        ".venv/a.sh",
        ".hidden.sh",
        "pkg/.cache/c.sh",
        "pkg/node_modules/b.sh",
        "pkg/ok.sh",
        "top.sh",
    ]

    found = _found(tmp_path, files, ".*\nnode_modules\n!.github\n")

    assert found == _dot(
        ".github/scripts/x.sh", ".github/workflows/w.sh", "pkg/ok.sh", "top.sh"
    )


def test_hidden_pattern_does_not_prune_the_start_directory(tmp_path: Path) -> None:
    """Exclusions only apply below the starting directory."""
    assert _found(tmp_path, ["top.sh", ".x/y.sh"], ".*\n") == _dot("top.sh")


def test_negation_cannot_reinclude_under_a_pruned_directory(tmp_path: Path) -> None:
    """Like gitignore, naming a file inside an excluded directory does not help."""
    files = [".github/scripts/x.sh", ".github/y.sh", "top.sh"]

    found = _found(tmp_path, files, ".*\n!.github/scripts\n!.github/scripts/x.sh\n")

    assert found == _dot("top.sh")


def test_negation_can_reinclude_a_file(tmp_path: Path) -> None:
    """A negation un-excludes a file whose directory was not pruned."""
    files = ["scripts/a_old.sh", "scripts/keep_old.sh", "scripts/new.sh"]

    found = _found(tmp_path, files, "*_old.sh\n!keep_old.sh\n")

    assert found == _dot("scripts/keep_old.sh", "scripts/new.sh")


@pytest.mark.parametrize("ignore", [".*\n!.github\n", "!.github\n.*\n"])
def test_line_order_does_not_matter(tmp_path: Path, ignore: str) -> None:
    """sort-ignore.sh reorders .shellignore, so a negation may come first."""
    files = [".github/a.sh", ".other/b.sh", "c.sh"]

    assert _found(tmp_path, files, ignore) == _dot(".github/a.sh", "c.sh")


def test_negation_only_excludes_nothing(tmp_path: Path) -> None:
    """With no ignore pattern there is nothing to un-ignore."""
    files = ["a.sh", "b/c.sh", ".d/e.sh"]

    assert _found(tmp_path, files, "!b\n!.d\n") == _dot(*files)


def test_anchored_negation_beats_a_broader_pattern(tmp_path: Path) -> None:
    """A path negation un-prunes only the directory it names."""
    files = ["lib/a.sh", "src/lib/b.sh", "keep/lib/c.sh"]

    found = _found(tmp_path, files, "lib\n!keep/lib\n")

    assert found == _dot("keep/lib/c.sh")


def test_tolerated_syntax(tmp_path: Path) -> None:
    """Comments, blank lines, ./ and / prefixes and trailing / are all fine."""
    files = [
        "#odd.sh",
        "build/a.sh",
        "dist/b.sh",
        "x/cache/c.sh",
        "out/d.sh",
        "keep.sh",
        "lib/e.sh",
    ]
    ignore = (
        "# a comment\n"
        "#*\n"
        "\n"
        "   \n"
        "./build/\n"
        "/dist\n"
        "cache/\n"
        "!/\n"
        "./\n"
        "/\n"
        "  out  \n"
        "lib"  # no trailing newline
    )

    found = _found(tmp_path, files, ignore)

    assert found == _dot("#odd.sh", "keep.sh")


def test_crlf_shellignore(tmp_path: Path) -> None:
    """Windows line endings do not stick to the patterns."""
    files = ["build/a.sh", "keep/b.sh", "x/node_modules/c.sh"]

    found = _found(tmp_path, files, b"build\r\nnode_modules\r\n")

    assert found == _dot("keep/b.sh")


@pytest.mark.parametrize("ignore", ["", "# only a comment\n", "\n\n"])
def test_shellignore_without_patterns_excludes_nothing(
    tmp_path: Path, ignore: str
) -> None:
    """An empty or comment-only .shellignore behaves like none."""
    files = ["a.sh", ".b/c.sh"]

    assert _found(tmp_path, files, ignore) == _dot(*files)


def test_only_the_shellignore_in_the_current_directory_counts(
    tmp_path: Path,
) -> None:
    """A .shellignore below the starting directory is not read."""
    files = ["sub/a.sh", "sub/inner/b.sh", "top.sh"]
    _touch(tmp_path, *files)
    (tmp_path / "sub" / ".shellignore").write_text("inner\n")

    assert _find(tmp_path) == _dot(*files)


def test_runs_under_other_working_directories(tmp_path: Path) -> None:
    """Paths are relative to wherever the script is run, not its location."""
    work = tmp_path / "work"
    _touch(work, "a.sh", "skip/b.sh")
    (work / ".shellignore").write_text("skip\n")

    assert _find(work) == ["./a.sh"]


# ---------------------------------------------------------------------------
# fix-sh.sh and lint-sh.sh
# ---------------------------------------------------------------------------


@dataclass
class ShellProject:
    """A project tree, the scripts under test and a log of fake tool calls."""

    root: Path
    bindir: Path
    log: Path
    env: dict[str, str]

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        """Run one of the copied scripts with the project as the cwd."""
        return subprocess.run(  # noqa: S603
            [_BASH, str(self.bindir / script)],
            cwd=self.root,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )

    def calls(self) -> list[dict]:
        """Return every fake tool call, oldest first."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


def _make_project(tmp_path: Path, bindir: Path) -> ShellProject:
    """Install fake tools and the scripts, and return a project to run them on."""
    root = tmp_path / "project"
    root.mkdir()
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for tool in ("shellcheck", "shellharden", "shfmt"):
        fake = fakebin / tool
        fake.write_text(_FAKE_TOOL.format(python=sys.executable))
        fake.chmod(0o755)
    bindir.mkdir(exist_ok=True)
    for name in _SCRIPT_NAMES:
        shutil.copy2(_BIN / name, bindir / name)
    log = tmp_path / "tools.jsonl"
    env = _base_env()
    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_TOOL_LOG"] = str(log)
    return ShellProject(root, bindir, log, env)


@pytest.fixture
def project(tmp_path: Path) -> ShellProject:
    """Build a project laid out like a child repo, scripts in its own ./bin."""
    shell_project = _make_project(tmp_path, tmp_path / "project" / "bin")
    _touch(
        shell_project.root,
        "keep.sh",
        "sub/also.sh",
        "vendor/skip.sh",
        ".hidden/skip.sh",
    )
    (shell_project.root / ".shellignore").write_text(".*\nvendor\n")
    return shell_project


@pytest.fixture
def empty_project(tmp_path: Path) -> ShellProject:
    """Build a project with nothing to process and scripts outside it."""
    shell_project = _make_project(tmp_path, tmp_path / "devenv-bin")
    _touch(shell_project.root, "vendor/skip.sh")
    (shell_project.root / "notes.txt").write_text("x")
    (shell_project.root / ".shellignore").write_text("vendor\n")
    return shell_project


@needs_mapfile
@pytest.mark.parametrize("script", sorted(_TOOL_RUNS))
def test_tools_get_the_found_files_and_not_the_excluded(
    project: ShellProject, script: str
) -> None:
    """Each tool is handed every found script and never an excluded one."""
    files = [
        "./bin/find-sh.sh",
        "./bin/fix-sh.sh",
        "./bin/lint-sh.sh",
        "./keep.sh",
        "./sub/also.sh",
    ]

    result = project.run(script)

    assert result.returncode == 0, result.stderr
    assert project.calls() == [
        {"tool": tool, "argv": [*flags, *files]} for tool, flags in _TOOL_RUNS[script]
    ]
    for call in project.calls():
        assert "./vendor/skip.sh" not in call["argv"]
        assert "./.hidden/skip.sh" not in call["argv"]


@needs_mapfile
@pytest.mark.parametrize("script", sorted(_TOOL_RUNS))
def test_no_files_runs_no_tools(empty_project: ShellProject, script: str) -> None:
    """With nothing to process the tools are not run, and the script succeeds."""
    result = empty_project.run(script)

    assert result.returncode == 0, result.stderr
    assert empty_project.calls() == []


@needs_mapfile
@pytest.mark.parametrize("script", sorted(_TOOL_RUNS))
def test_finder_is_found_next_to_the_script_not_in_the_cwd(
    empty_project: ShellProject, script: str
) -> None:
    """A finder in the working directory's own bin is not the one that runs."""
    _touch(empty_project.root, "keep.sh")
    decoy = empty_project.root / "bin" / "find-sh.sh"
    decoy.parent.mkdir()
    decoy.write_text("#!/usr/bin/env bash\nprintf './decoy.sh\\0'\n")
    decoy.chmod(0o755)

    result = empty_project.run(script)

    assert result.returncode == 0, result.stderr
    for call in empty_project.calls():
        assert "./keep.sh" in call["argv"]
        assert "./decoy.sh" not in call["argv"]


@needs_mapfile
@pytest.mark.parametrize("script", sorted(_TOOL_RUNS))
def test_a_failing_finder_fails_the_script(
    empty_project: ShellProject, script: str
) -> None:
    """A finder error must not look like zero files and a passing lint."""
    finder = empty_project.bindir / "find-sh.sh"
    finder.write_text(f"#!/usr/bin/env bash\nprintf './a.sh\\0'\nexit {_FINDER_EXIT}\n")

    result = empty_project.run(script)

    assert result.returncode == _FINDER_EXIT
    assert empty_project.calls() == []
