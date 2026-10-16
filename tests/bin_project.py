"""
A child project for the tests that run the copy/*/bin scripts.

Each test copies the scripts it needs into a project's ./bin and runs them as
make does, by their #!/usr/bin/env bash, once per bash the bash fixture finds,
macOS's stock 3.2 among them. PATH holds only fake tools, that bash and the
system directories, so no real linter, uv or bun is ever run. The fakes log
their argv, working directory and a few environment variables.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

COPY = Path(__file__).resolve().parent.parent / "copy"
_LOGGED_ENV = ("DEBUG", "PYTHONDEVMODE", "PYTHONPATH")
USAGE_EXIT = 2
FAIL_EXIT = 5

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


def write_fake(path: Path) -> None:
    """Write a fake tool that logs its call to FAKE_TOOL_LOG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FAKE_TOOL.format(python=sys.executable, logged_env=_LOGGED_ENV))
    path.chmod(0o755)


def make_tree(root: Path, *names: str) -> None:
    """Create each named file under root."""
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
            (COPY / feature / "bin" / name).copy(
                self.root / "bin" / name, preserve_metadata=True
            )

    def fake(self, *tools: str) -> None:
        """Put fake tools on PATH."""
        for tool in tools:
            write_fake(self.fakebin / tool)

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
