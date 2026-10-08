# devenv News

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
