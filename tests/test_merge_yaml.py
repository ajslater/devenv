"""
merge_yaml merges devenv's YAML templates into a child's own files.

The child's file is the last one merged, so it is the base of the result: its
comments, tags, anchors, scalar spellings and key order survive, and the
templates only add what it lacks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import merge_yaml

_ROOT = Path(__file__).resolve().parent.parent
_MKDOCS = _ROOT / "merge" / "docs" / "mkdocs.yml"
_READTHEDOCS = _ROOT / "merge" / "docs" / ".readthedocs.yaml"
_COMPOSE = _ROOT / "merge" / "ci" / "compose.yaml"
# Realistic child files for each shipped template.
_PROJECTS = {
    _MKDOCS: """\
# The demo's docs.
site_name: Démo — docs
theme:
  name: material  # not the template's mkdocs theme
  logo: img/logo.svg

plugins:
  - search
  - minify:
      minify_html: false

markdown_extensions:
  - pymdownx.emoji:
      emoji_index: !!python/name:material.extensions.emoji.twemoji
      emoji_generator: !!python/name:material.extensions.emoji.to_svg
  - toc:
      permalink: "#"

extra:
  analytics:
    property: !ENV [GOOGLE_ANALYTICS_KEY, ""]

nav:
  - Home: index.md
  - Guide:
      - guide/install.md
      - guide/usage.md
""",
    _READTHEDOCS: """\
# Read the Docs configuration file
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.13"

python:
  install:
    - requirements: requirements-docs.txt
""",
    _COMPOSE: """\
x-defaults: &defaults
  restart: no
  environment:
    - TZ=UTC

services:
  ci:
    <<: *defaults
    build:
      context: .
      target: demo-ci
    image: ${CI_IMAGE}

  web:
    <<: *defaults
    image: demo
    ports:
      - "8000:8000"
""",
}


def _merge(tmp_path: Path, template: str, project: str, *args: str) -> str:
    """Merge template into project with the CLI, as update_devenv does."""
    template_path = tmp_path / "template.yaml"
    template_path.write_text(template)
    project_path = tmp_path / "project.yaml"
    project_path.write_text(project)
    argv = [str(template_path), str(project_path), "-o", str(project_path)]
    merge_yaml.main([*argv, *args])
    return project_path.read_text()


@pytest.mark.parametrize("template", _PROJECTS, ids=lambda path: path.name)
def test_template_alone_is_written_as_is(tmp_path: Path, template: Path) -> None:
    """A child without the file gets the template exactly as shipped."""
    output = tmp_path / template.name
    merge_yaml.main([str(template), "-o", str(output)])

    assert output.read_text() == template.read_text()


@pytest.mark.parametrize(
    ("template", "project"), _PROJECTS.items(), ids=[path.name for path in _PROJECTS]
)
def test_second_merge_changes_nothing(
    tmp_path: Path, template: Path, project: str
) -> None:
    """update-devenv runs again and again, so its output is a fixed point."""
    path = tmp_path / template.name
    path.write_text(project)
    argv = [str(template), str(path), "-o", str(path)]

    merge_yaml.main(argv)
    first = path.read_bytes()
    merge_yaml.main(argv)

    assert path.read_bytes() == first


def test_mkdocs_tags_survive(tmp_path: Path) -> None:
    """The python/name and !ENV tags mkdocs uses load and are written as is."""
    project = _PROJECTS[_MKDOCS]

    merged = _merge(tmp_path, _MKDOCS.read_text(), project)

    assert "emoji_index: !!python/name:material.extensions.emoji.twemoji\n" in merged
    assert 'property: !ENV [GOOGLE_ANALYTICS_KEY, ""]\n' in merged


def test_comments_survive(tmp_path: Path) -> None:
    """Whole-line and end-of-line comments stay where the child put them."""
    project = "# Header.\na: 1  # one\n# Before b.\nb: 2\n"

    merged = _merge(tmp_path, "c: 3\n", project)

    assert merged == "# Header.\na: 1  # one\n# Before b.\nb: 2\nc: 3\n"


def test_anchors_and_aliases_survive(tmp_path: Path) -> None:
    """Anchors, aliases and merge keys are not expanded."""
    project = _PROJECTS[_COMPOSE]

    merged = _merge(tmp_path, _COMPOSE.read_text(), project)

    assert merged.startswith(project[: project.index("services:")])
    assert merged.count("<<: *defaults\n") == project.count("<<: *defaults\n")


def test_unaliased_anchor_survives(tmp_path: Path) -> None:
    """An anchor that nothing aliases yet is still written back."""
    project = "x-env: &env\n  - TZ=UTC\nservices: {}\n"

    merged = _merge(tmp_path, "version: 2\n", project)

    assert merged == f"{project}version: 2\n"


# A template that adds an environment variable to the ci service only.
_CI_ENV_TEMPLATE = "services:\n  ci:\n    environment:\n      - PYTHONUNBUFFERED=1\n"
# Projects whose services share one environment, through a `<<` merge key
# and through plain aliases.
_SHARED_ENV = {
    "merge-key": """\
x-defaults: &defaults
  restart: no
  environment:
    - TZ=UTC

services:
  ci:
    <<: *defaults
    image: ${CI_IMAGE}

  web:
    <<: *defaults
    image: demo
""",
    "alias": """\
x-env: &env
  - TZ=UTC

services:
  ci:
    environment: *env

  web:
    environment: *env
""",
}


def test_merge_key_inherited_value_is_copied_not_changed(tmp_path: Path) -> None:
    """
    The template's addition to an inherited value goes to that service only.

    Merging into the value a `<<` merge key brings in would change the anchor,
    and so every other service that shares it.
    """
    project = _SHARED_ENV["merge-key"]

    merged = _merge(tmp_path, _CI_ENV_TEMPLATE, project)

    ci_env = "    environment:\n      - TZ=UTC\n      - PYTHONUNBUFFERED=1\n"
    image = "    image: ${CI_IMAGE}\n"
    assert merged == project.replace(image, image + ci_env)
    services = merge_yaml.load_yaml_text(merged)["services"]
    assert services["ci"]["environment"] == ["TZ=UTC", "PYTHONUNBUFFERED=1"]
    assert services["web"]["environment"] == ["TZ=UTC"]


def test_aliased_value_is_copied_not_changed(tmp_path: Path) -> None:
    """The template's addition to an alias goes to that key only."""
    project = _SHARED_ENV["alias"]

    merged = _merge(tmp_path, _CI_ENV_TEMPLATE, project)

    assert merged == project.replace(
        "  ci:\n    environment: *env\n",
        "  ci:\n    environment:\n      - TZ=UTC\n      - PYTHONUNBUFFERED=1\n",
    )
    services = merge_yaml.load_yaml_text(merged)["services"]
    assert services["web"]["environment"] == ["TZ=UTC"]


@pytest.mark.parametrize("project", _SHARED_ENV.values(), ids=_SHARED_ENV.keys())
def test_shared_value_the_template_does_not_add_to_stays_shared(
    tmp_path: Path, project: str
) -> None:
    """A shared value the template already matches keeps its alias or `<<`."""
    template = "services:\n  ci:\n    environment:\n      - TZ=UTC\n"

    merged = _merge(tmp_path, template, project)

    assert merged == project


@pytest.mark.parametrize("project", _SHARED_ENV.values(), ids=_SHARED_ENV.keys())
def test_second_merge_into_a_shared_value_changes_nothing(
    tmp_path: Path, project: str
) -> None:
    """Once copied, the service's own value is a fixed point."""
    first = _merge(tmp_path, _CI_ENV_TEMPLATE, project)

    assert _merge(tmp_path, _CI_ENV_TEMPLATE, first) == first


def test_remove_values_copies_a_shared_value_too() -> None:
    """Retiring a value from one service leaves the others sharing it alone."""
    data = merge_yaml.load_yaml_text(
        _SHARED_ENV["alias"].replace("  - TZ=UTC\n", "  - TZ=UTC\n  - OLD=1\n")
    )
    retired = merge_yaml.load_yaml_text(
        "services:\n  ci:\n    environment:\n      - OLD=1\n"
    )

    merge_yaml.remove_values(data, retired)

    assert merge_yaml.dump_yaml(data) == _SHARED_ENV["alias"].replace(
        "  - TZ=UTC\n", "  - TZ=UTC\n  - OLD=1\n"
    ).replace(
        "  ci:\n    environment: *env\n", "  ci:\n    environment:\n      - TZ=UTC\n"
    )


def test_scalar_spellings_survive(tmp_path: Path) -> None:
    """A compose `restart: no` stays `no`, not `false`; quotes stay quotes."""
    project = "restart: no\npython: \"3\"\nport: '8000'\n"

    merged = _merge(tmp_path, "restart: always\n", project)

    assert merged == project


def test_unicode_is_not_escaped(tmp_path: Path) -> None:
    """Non-ASCII text is written as text, not as escapes."""
    project = "site_name: Démo — docs\n"

    merged = _merge(tmp_path, "site_name: Demo\n", project)

    assert merged == project


def test_project_key_order_wins(tmp_path: Path) -> None:
    """The child's keys keep its order; keys it lacks go at the end."""
    template = "a: 1\nnested:\n  x: 1\n  y: 2\nb: 2\n"
    project = "z: 26\nnested:\n  y: 25\n  w: 23\nb: 0\n"

    merged = _merge(tmp_path, template, project)

    assert merged == "z: 26\nnested:\n  y: 25\n  w: 23\n  x: 1\nb: 0\na: 1\n"


def test_added_keys_go_before_the_gap_that_ends_their_mapping(
    tmp_path: Path,
) -> None:
    """A blank line or comment closing a mapping still closes it."""
    template = "theme:\n  name: mkdocs\n  strict: true\n"
    project = "theme:\n  name: material  # ours\n\n# Docs pages.\nnav:\n  - index.md\n"

    merged = _merge(tmp_path, template, project)

    assert merged == (
        "theme:\n  name: material  # ours\n  strict: true\n"
        "\n# Docs pages.\nnav:\n  - index.md\n"
    )


def test_template_list_items_reach_an_existing_project(tmp_path: Path) -> None:
    """A plugin new to the template is added after the child's own."""
    template = "plugins:\n  - search\n  - offline\n"
    project = "plugins:\n  - tags\n  - search\n"

    merged = _merge(tmp_path, template, project)

    assert merged == "plugins:\n  - tags\n  - search\n  - offline\n"


def test_list_merge_adds_each_template_item_once(tmp_path: Path) -> None:
    """Template items already in the child, or repeated, are not duplicated."""
    template = "volumes:\n  - ./dist:/app/dist\n  - ./a:/a\n  - ./a:/a\n"
    project = "volumes:\n  - ./dist:/app/dist\n"

    merged = _merge(tmp_path, template, project)

    assert merged == "volumes:\n  - ./dist:/app/dist\n  - ./a:/a\n"


@pytest.mark.parametrize(
    "project",
    [
        "plugins:\n  - minify\n  - search\n",
        "plugins:\n  - minify:\n      minify_js: false\n  - search\n",
    ],
    ids=["bare", "configured"],
)
def test_a_plugin_named_either_way_is_one_plugin(tmp_path: Path, project: str) -> None:
    """`minify` and `minify: {...}` name the same plugin; the child's form wins."""
    template = "plugins:\n  - minify:\n      minify_html: true\n  - search\n"

    merged = _merge(tmp_path, template, project)

    assert merged == project


def test_added_list_items_go_before_the_gap_that_ends_their_list(
    tmp_path: Path,
) -> None:
    """A blank line after a list still follows it once items are added."""
    template = "plugins:\n  - search\n  - offline\n"
    project = "plugins:\n  - minify:\n      minify_html: true\n\nnav:\n  - index.md\n"

    merged = _merge(tmp_path, template, project)

    assert merged == (
        "plugins:\n  - minify:\n      minify_html: true\n  - search\n  - offline\n"
        "\nnav:\n  - index.md\n"
    )


def test_replace_list_strategy_keeps_the_project_list(tmp_path: Path) -> None:
    """With --list-strategy replace, the child's list replaces the template's."""
    template = "plugins:\n  - search\n  - offline\n"
    project = "plugins:\n  - tags\n"

    merged = _merge(tmp_path, template, project, "--list-strategy", "replace")

    assert merged == project


def test_empty_project_file_gets_the_template(tmp_path: Path) -> None:
    """An empty child file merges like a missing one."""
    merged = _merge(tmp_path, _MKDOCS.read_text(), "")

    assert merged == _MKDOCS.read_text()


def test_non_mapping_root_is_rejected(tmp_path: Path) -> None:
    """A file whose root is not a mapping cannot be merged."""
    with pytest.raises(TypeError, match="mapping"):
        _merge(tmp_path, "a: 1\n", "- a\n")


def test_remove_values_drops_listed_items(tmp_path: Path) -> None:
    """--remove-values drops the values it lists at the same key path."""
    remove = tmp_path / "remove.yaml"
    remove.write_text("theme:\n  features:\n    - retired\n")
    template = "theme:\n  features:\n    - kept\n    - retired\n"
    project = "theme:\n  features:\n    - ours\n    - retired\n"

    merged = _merge(tmp_path, template, project, "--remove-values", str(remove))

    assert merged == "theme:\n  features:\n    - ours\n    - kept\n"


def test_remove_values_retires_a_plugin_in_either_form() -> None:
    """A bare plugin name also retires that plugin's configured form."""
    data = merge_yaml.load_yaml_text(
        "plugins:\n  - minify:\n      minify_html: true\n  - search\n  - offline\n"
    )
    retired = merge_yaml.load_yaml_text("plugins:\n  - minify\n  - offline\n")

    merge_yaml.remove_values(data, retired)

    assert merge_yaml.dump_yaml(data) == "plugins:\n  - search\n"


def test_remove_values_prunes_emptied_containers() -> None:
    """A list or mapping emptied by retirement goes, instead of lingering."""
    data = merge_yaml.load_yaml_text(
        "site_name: Demo\nextra:\n  css:\n    - old.css\nextra_css:\n  - old.css\n"
    )
    retired = merge_yaml.load_yaml_text(
        "extra:\n  css:\n    - old.css\nextra_css:\n  - old.css\n"
    )

    merge_yaml.remove_values(data, retired)

    assert merge_yaml.dump_yaml(data) == "site_name: Demo\n"


def test_remove_values_ignores_what_is_not_there() -> None:
    """Missing keys, mismatched types and unlisted values are left alone."""
    text = "a:\n  - x\nb: scalar\nc:\n  d: 1\n"
    data = merge_yaml.load_yaml_text(text)
    retired = merge_yaml.load_yaml_text("a:\n  - y\nb:\n  - scalar\nc: 1\nz:\n  - x\n")

    merge_yaml.remove_values(data, retired)

    assert merge_yaml.dump_yaml(data) == text


def test_remove_values_keeps_the_gap_after_a_shortened_list() -> None:
    """Dropping a list's last item keeps the blank line that closed it."""
    data = merge_yaml.load_yaml_text(
        "plugins:\n  - search\n  - old\n\nnav:\n  - a.md\n"
    )
    retired = merge_yaml.load_yaml_text("plugins:\n  - old\n")

    merge_yaml.remove_values(data, retired)

    assert merge_yaml.dump_yaml(data) == "plugins:\n  - search\n\nnav:\n  - a.md\n"
