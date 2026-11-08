"""
news_normalize's callouts and Python requirement moves.

A `### 💥 Breaking Changes` section's items go inside a `> [!WARNING]`, a
`### 🗑️ Deprecated` section's inside a `> [!NOTE]`, and a yanked version gets
a `> [!CAUTION]` body, in the form Prettier keeps: the marker, a bare `>` line,
then the body. An item that raises or drops a required Python version moves to
Breaking Changes. A converted file passes through unchanged, so a callout
someone rewrote by hand survives a re-run.
"""

from pathlib import Path

import pytest

from scripts import news_normalize

_NEWS = Path(__file__).resolve().parent.parent / "NEWS.md"
_PLAIN = """\
# News

## v2.0.0

### 💥 Breaking Changes

- The HTTP API moved from `/api/v3/` to `/api/v4/`, and every client must
  change its base URL.
- Python 3.15 is required.

### ✨ Added

- A server folder picker.
"""
_WRAPPED = """\
# News

## v2.0.0

### 💥 Breaking Changes

> [!WARNING]
>
> - The HTTP API moved from `/api/v3/` to `/api/v4/`, and every client must
>   change its base URL.
> - Python 3.15 is required.

### ✨ Added

- A server folder picker.
"""


def _version(header: str, body: str = "") -> str:
    """Return a NEWS.md whose last version has header and body."""
    return f"# News\n\n{header}\n" + (f"\n{body}" if body else "")


def test_wraps_breaking_changes() -> None:
    """A Breaking Changes section's items go inside a WARNING."""
    assert news_normalize.convert(_PLAIN) == _WRAPPED


def test_keeps_wrapped_breaking_changes() -> None:
    """A section already in its WARNING is not wrapped again."""
    assert news_normalize.convert(_WRAPPED) == _WRAPPED


def test_nested_bullets_keep_their_indent() -> None:
    """Nested bullets sit four spaces in, inside the quote."""
    plain = _version(
        "## v1.11.0",
        """\
### 💥 Breaking Changes

- Unified configuration:
    - `CODEX_CONFIG_DIR` is now `CODEX_CONFIG`.
    - `hypercorn.toml` is gone.
- Python 3.15 is required.
""",
    )
    wrapped = _version(
        "## v1.11.0",
        """\
### 💥 Breaking Changes

> [!WARNING]
>
> - Unified configuration
>     - `CODEX_CONFIG_DIR` is now `CODEX_CONFIG`.
>     - `hypercorn.toml` is gone.
> - Python 3.15 is required.
""",
    )
    assert news_normalize.convert(plain) == wrapped
    assert news_normalize.convert(wrapped) == wrapped


@pytest.mark.parametrize(
    ("header", "sentence"),
    [
        ("## v1.6.18 - Yanked, broken reader", "Yanked, broken reader."),
        ("## v1.10.4-7 - Broken releases", "Broken releases."),
        ("## v1.10.1 - mistaken release", "Mistaken release."),
        ("## v1.9.8 - Bad release, does not start", "Bad release, does not start."),
        ("## v0.4.1 - Yanked.", "Yanked."),
    ],
)
def test_yanked_version_gets_a_caution(header: str, sentence: str) -> None:
    """A yanked version's body is a CAUTION repeating its subtitle."""
    caution = _version(header, f"> [!CAUTION]\n>\n> {sentence}\n")
    assert news_normalize.convert(_version(header)) == caution
    assert news_normalize.convert(caution) == caution


def test_legacy_yanked_note_gets_a_caution() -> None:
    """A legacy status note becomes the subtitle, then the CAUTION."""
    legacy = _version("## v1.6.18", "- Yanked. Broken Reader.\n")
    caution = _version(
        "## v1.6.18 - Yanked, broken reader",
        "> [!CAUTION]\n>\n> Yanked, broken reader.\n",
    )
    assert news_normalize.convert(legacy) == caution


def test_keeps_a_hand_written_caution() -> None:
    """A reworded CAUTION, wrapped over two lines, stays verbatim."""
    caution = _version(
        "## v1.6.18 - Yanked, broken reader",
        """\
> [!CAUTION]
>
> The reader does not open comics, so every page is blank. Use v1.6.19 or
> later.

## v1.6.17

### 🐛 Fixed

- The reader opens comics.
""",
    )
    assert news_normalize.convert(caution) == caution


@pytest.mark.parametrize(
    "news",
    [
        _version("## v0.5.8 - Version bump for the 0.5.7 upload mistake"),
        _version("## v1.1.9"),
        _version(
            "## v1.2.0 - Faster scans",
            "### ✨ Added\n\n- A folder picker.\n\n### 🐛 Fixed\n\n- A crash.\n",
        ),
    ],
)
def test_leaves_other_versions_alone(news: str) -> None:
    """A version with no Breaking Changes and no yanked subtitle is unchanged."""
    assert news_normalize.convert(news) == news


def test_wraps_deprecated() -> None:
    """A Deprecated section's items go inside a NOTE, once."""
    plain = _version("## v2.4.0", "### 🗑️ Deprecated\n\n- `dump()`, use `dumpf()`.\n")
    wrapped = _version(
        "## v2.4.0", "### 🗑️ Deprecated\n\n> [!NOTE]\n>\n> - `dump()`, use `dumpf()`.\n"
    )
    assert news_normalize.convert(plain) == wrapped
    assert news_normalize.convert(wrapped) == wrapped


def _quote(text: str) -> str:
    """Return text with every line prefixed `> `."""
    return "".join(f"> {line}\n" for line in text.split("\n"))


@pytest.mark.parametrize(
    "item",
    [
        "- Require Python 3.11.",
        "- Require python 3.10",
        "- Requires Python 3.11 or later.",
        "- Python version now >=3.9",
        "- Django 6 requires python >=3.12.",
        "- Python 3.15 is required.",
        "- Drop support for Python 3.10.",
        "- Stop supporting python 2",
        (
            "- The confuse library dependency doesn't support Python 3.14. So neither"
            " does\n  picopt :("
        ),
        "- Don't support Python 3.14 until dependencies do.",
        "- No longer supports\n  Python 3.10.",
    ],
)
def test_moves_a_python_requirement(item: str) -> None:
    """A Python requirement item moves to a new Breaking Changes, once."""
    plain = _version("## v2.0.0", f"### ♻️ Changed\n\n{item}\n")
    moved = _version(
        "## v2.0.0", f"### 💥 Breaking Changes\n\n> [!WARNING]\n>\n{_quote(item)}"
    )
    assert news_normalize.convert(plain) == moved
    assert news_normalize.convert(moved) == moved


@pytest.mark.parametrize(
    "breaking",
    ["- The config file moved.", "> [!WARNING]\n>\n> - The config file moved."],
)
def test_moves_a_python_requirement_into_breaking_changes(breaking: str) -> None:
    """The item joins the end of an existing Breaking Changes, wrapped or not."""
    plain = _version(
        "## v5.0.0",
        f"""\
### 💥 Breaking Changes

{breaking}

### ✨ Added

- A folder picker.

### 🧑‍💻 Developer

- Require Python 3.11.
- Requires python-dateutil 4.0.
""",
    )
    moved = _version(
        "## v5.0.0",
        """\
### 💥 Breaking Changes

> [!WARNING]
>
> - The config file moved.
> - Require Python 3.11.

### ✨ Added

- A folder picker.

### 🧑‍💻 Developer

- Requires python-dateutil 4.0.
""",
    )
    assert news_normalize.convert(plain) == moved
    assert news_normalize.convert(moved) == moved


@pytest.mark.parametrize(
    "item",
    [
        "- Support Python 3.14",
        "- Python 3.14 support.",
        "- Better Python 3.13 support.",
        "- Supports Python 3.15 and requires python-dateutil 3.0.",
        "- Docker images now use Python 3.15",
        "- Now compatible with python 3.10.",
        "- Requires python-dateutil v4.0",
        "- Require typing-extensions only on Python 3.11.",
        (
            "- Requires python-dateutil 4.0 and treestamps 5.2.1, and typing-extensions"
            " only\n  on Python 3.11."
        ),
        "- Only import typing extensions on Python < 3.12",
        "- Removed dependence on Python 3.11",
    ],
)
def test_leaves_other_python_items_alone(item: str) -> None:
    """Added support and other packages' requirements stay where they are."""
    news = _version("## v1.8.1", f"### 🧑‍💻 Developer\n\n{item}\n")
    assert news_normalize.convert(news) == news


def test_deprecated_keeps_python_items() -> None:
    """A deprecated Python version still works, so it stays in Deprecated."""
    news = _version(
        "## v2.4.0",
        "### 🗑️ Deprecated\n\n> [!NOTE]\n>\n> - Drop Python 3.10 in v3.0.0.\n",
    )
    assert news_normalize.convert(news) == news


def test_converts_own_news_idempotently() -> None:
    """A second run over devenv's own NEWS.md changes nothing."""
    once = news_normalize.convert(_NEWS.read_text())
    assert news_normalize.convert(once) == once
