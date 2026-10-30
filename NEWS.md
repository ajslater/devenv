# devenv News

## v0.2.11

- Features
    - complexipy 8.1, which parses Python 3.15. `make fix` applies its refactors
      to functions over the complexity limit; `make fix-complexity` applies only
      those.
    - `make prune-branches` deletes local branches except `main`, `master`,
      `develop`, `pre-release`, checked-out ones and those in `.keep-branches`.
    - With frontend, the root lint leaves `frontend/` to its own lint.
    - CI uploads the coverage HTML report.
- Fixes
    - `__snapshots__` is no longer gitignored, so snapshot baselines can be
      committed.
    - `bin/release-tag.sh publish` no longer fails at random deciding whether a
      release is the latest.
    - `bin/manage.py` run directly imports the project from its own root, not
      another installed copy.
    - `make update-devenv` formats Makefiles with mbake 1.5, as `make fix` does,
      so the two no longer disagree about the final newline.

## v0.2.10

- Fixes
    - Workflows are linted in the CI image too. Without `.git`, calls into local
      reusable workflows are not checked.

## v0.2.9

- Features
    - CI lints shell scripts, Dockerfiles and workflows: a missing lint tool
      fails instead of being skipped. Add shellcheck, shellharden, shfmt,
      hadolint, dockerfmt and actionlint to your Dockerfile's CI stage (recipe
      under GitHub Actions in devenv's README); native mode installs them with
      brew.

## v0.2.8

- Features
    - GitHub Actions jobs run on `ubuntu-latest`, and Read the Docs builds on
      `ubuntu-lts-latest`. A `.readthedocs.yaml` still on `ubuntu-24.04` moves
      to it; any other `build.os` is left alone.

## v0.2.7

- Fixes
    - common no longer needs node_root; fix and lint skip missing `package.json`
      scripts.

## v0.2.6

- Fixes
    - `[tool.pytest.ini_options]` is deleted from `pyproject.toml`. Move any
      settings of your own from it (see `git diff pyproject.toml`) to
      `[tool.pytest]` as native TOML values.

## v0.2.5

- Fixes
    - ESLint ignores build output, caches and venvs in subdirectories too, such
      as `frontend/dist/`.

## v0.2.4

- Features
    - New projects start on Python 3.15.
    - devenv's own scripts run on Python 3.15, which uv installs, and read TOML
      1.1 pyproject files.
    - ruff 0.17 is the lint floor.

## v0.2.3

- Fixes
    - `bin/collectstatic.sh` asks django whether there is anything to collect
      and skips, saying why, when `django.contrib.staticfiles` is not installed,
      `STATIC_ROOT` is unset or no finder has files. It used to fail
      `make build` with "Unknown command" in a project with no static files.
    - The python pyproject template no longer ships one project's sdist globs
      (`img/**`, `mock_comics/**`, `.picopt_treestamps.yaml`, `.env.platforms`).
      The docs and frontend features now add their own (`docs/**`, `mkdocs.yml`,
      `.readthedocs.yaml`; `frontend/**`). `package-lock.json` is retired from
      `source-include` and the codespell skip list.
    - `.claude` is retired from the ignore files. Only
      `.claude/settings.local.json` and `.claude/worktrees/` are ignored now, so
      a project's `.claude/rules/`, `settings.json`, commands and agents can be
      committed, which is what Claude Code expects.

## v0.2.2

- Fixes
    - django no longer needs frontend. collectstatic still builds the frontend
      first when the frontend feature or the project defines `build-frontend`.

## v0.2.1

- Fixes
    - common no longer needs python, and runs the latest mbake.

## v0.2.0

- Breaking Changes
    - Features declare what they need and update-devenv refuses an incomplete
      set: django needs frontend and python; gha_std needs ci; ci and docs need
      python; common needs python and node_root.
    - `scripts/add_makefiles.py` is now `scripts/add_features.py`.
    - `make fix-sh` and `make lint-sh` run `bin/sh-tools.sh`; `fix-sh.sh`,
      `lint-sh.sh`, `lint-darwin.sh` and `type-python.sh` are retired.
    - django's `prod-server` target moved to codex, the one project it ran.
    - Value retirement files are `<template>.remove<ext>` siblings.
- Features
    - update-devenv stamps `.devenv-version`, prints devenv news since the last
      update, and no longer deletes a file retired before that.
    - Merges keep the project's comments, order, formatting and YAML tags, and
      add new template list items to existing projects.
    - A missing lint tool prints `skipped: <tool> not installed` instead of
      passing silently, and shell, docker and complexity checks run off macOS.
    - `UPDATE_DEVENV_FLAGS=--no-update-deps` skips `bun update`.
    - django ships `bin/collectstatic.sh` and declares djlint.
    - Third-party GitHub Actions are pinned by SHA and every job has a timeout.
- Fixes
    - init and convert keep existing files and include every feature asked for.
    - A second update changes nothing.
    - pyproject descriptions with commas, pytest `addopts` order, author tables
      and project-only package.json script steps survive merges.
    - The lint holes: every Dockerfile, shell script and django template is
      checked, outside `node_modules` too.
    - `bin/` scripts run on macOS's stock bash 3.2, and release tagging on its
      python 3.9.
    - `make help` no longer runs targets together, and stays quiet without a
      terminal.
    - Ignore files sort the same on every machine.
    - The develop CI gate no longer runs for branches like `vulture-fix`, and a
      main CI run is never cancelled between the PyPI upload and the tag.
