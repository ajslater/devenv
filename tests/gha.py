"""Paths and loaders for the tests of devenv's GitHub Actions."""

from pathlib import Path
from typing import Any

import yaml

_TESTS = Path(__file__).resolve().parent
ROOT = _TESTS.parent
CI = ROOT / "copy" / "ci"
WORKFLOWS = CI / ".github" / "workflows"
ACTIONS = CI / ".github" / "actions"
STD_CALLER = ROOT / "copy" / "gha_std" / ".github" / "workflows" / "ci.yml"
CALLERS = {
    "std": STD_CALLER,
    "codex": _TESTS / "fixtures" / "gha" / "codex-ci.yml",
    "native": _TESTS / "fixtures" / "gha" / "native-ci.yml",
}


def load(path: Path) -> dict[Any, Any]:
    """Parse a workflow or action."""
    return yaml.safe_load(path.read_text())


def trigger(workflow: dict[Any, Any]) -> Any:
    """Return a workflow's on: value."""
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow[True]
