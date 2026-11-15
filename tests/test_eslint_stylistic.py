"""
The @stylistic rules that node_root's shipped ESLint base config leaves on.

configs.all turns on every rule @stylistic/eslint-plugin ships, and
eslint-config-prettier turns off the ones Prettier owns, but only those it
knows. A rule from a newer @stylistic release stays on, and when it fights
Prettier, `make fix` cannot clear it and `make lint` fails in every node_root
project. Pinning the set makes the bump that adds such a rule fail here first.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BASE_CONFIG = _ROOT / "copy" / "node_root" / "cfg" / "eslint.config.base.js"
_ESLINT = _ROOT / "node_modules" / "eslint" / "bin" / "eslint.js"
_NODE = shutil.which("node") or ""
_OFF = (0, "off")

# Each survives eslint-config-prettier and agrees with Prettier.
_KEPT = frozenset(
    (
        "@stylistic/lines-between-class-members",
        "@stylistic/padding-line-between-statements",
        "@stylistic/spaced-comment",
    )
)

pytestmark = pytest.mark.skipif(
    not (_NODE and _ESLINT.is_file()), reason="needs node and bun install"
)


def _severity(entry: int | str | list) -> int | str:
    return entry[0] if isinstance(entry, list) else entry


def test_only_the_kept_stylistic_rules_are_on() -> None:
    """A @stylistic rule that joins or leaves the enabled set fails here."""
    result = subprocess.run(  # noqa: S603
        [
            _NODE,
            str(_ESLINT),
            "--config",
            str(_BASE_CONFIG),
            "--print-config",
            "probe.js",
        ],
        check=True,
        capture_output=True,
        cwd=_ROOT,
        text=True,
    )
    rules = json.loads(result.stdout)["rules"]
    enabled = {
        name
        for name, entry in rules.items()
        if name.startswith("@stylistic/") and _severity(entry) not in _OFF
    }
    assert enabled == _KEPT, (
        "Turn a rule that fights Prettier off in the base config's"
        " devenv/prettier-owns-stylistic block; add one that agrees to _KEPT."
    )
