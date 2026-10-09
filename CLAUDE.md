# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What This Repo Is

A **boilerplate parent configuration system** that houses generic configs and
scripts for managing development environments. It sits as a sibling directory
(`../devenv`) to child projects that reference it. It non-destructively merges
parent configs into child projects via feature-flag-driven scripts, and can be
re-run at any time (`make update-devenv`). README.md documents it for users.

This repo dogfoods its own configuration system: its root Makefile enables the
`common`, `python`, `node` and `node_root` features with `DEVENV_SRC` set to
itself.

## Edit Sources, Not Outputs

This repo dogfoods itself, so most root-level files are **generated outputs**,
not sources. Editing them directly is almost always wrong — your changes will be
clobbered the next time `make update-devenv` runs, and CI fails when the root
drifts from its sources.

**Never edit directly** (downstream — regenerated from sources):

- `./bin/` — sourced from `copy/*/bin/`
- `./cfg/` — sourced from `copy/*/cfg/`, except `cfg/devenv.mk`

**Rarely edit directly** (downstream — merged from sources):

- `./pyproject.toml` — merged from `merge/*/pyproject-template.toml`
- `./package.json` — merged from `merge/*/package.json`
- The root dotfiles (`.gitignore`, `.prettierignore`, ...) — merged from
  `merge/*/`

Values only this repo needs (its own dependency groups, `extraPaths`) are fine
to add to the root `pyproject.toml`; the merge keeps them.

**Hand-maintained** at the root: `Makefile`, `cfg/devenv.mk`,
`eslint.config.js`, `NEWS.md` and `.github/workflows/ci.yml`.

**Edit these instead** (the actual sources):

- `copy/` — files copied wholesale into child projects (and into this repo's own
  root, since it dogfoods)
- `merge/` — config templates merged into child projects
- `init/` — one-time starter files for new projects
- `scripts/` — the merge/copy machinery itself

When in doubt, find the file under `copy/`, `merge/`, or `init/` first. If a
root-level file has a counterpart in one of those directories, the root file is
the output.

## Common Commands

```bash
make install            # uv sync all groups, bun install
make fix                # mbake, eslint/prettier, sort ignore files, shell fixes, ruff
make lint               # the same checks without fixing, plus basedpyright, vulture,
                        # complexity and codespell
make ty                 # ty type check
make test               # pytest; T=tests/test_foo.py for one file
uv run pytest -q tests/test_pipeline.py   # without coverage noise
make update-devenv UPDATE_DEVENV_FLAGS=--no-update-deps   # dogfood the root
```

Run `make fix lint ty test` before committing. After editing `copy/` or
`merge/`, run the dogfood update and commit the root outputs it changes.

## Architecture

### Feature-Flag System

Child project Makefiles include `cfg/<feature>.mk`, which sets and exports
`DEVENV_<FEATURE>`. `scripts/_devenv_common.py` `FEATURES` is the one registry:
each feature's requirements, whether new projects get it, and the canonical
include order. Update and `add_features.py` refuse an unknown feature or an
unmet requirement.

| Feature     | Config             | Purpose                                        | Requires    |
| ----------- | ------------------ | ---------------------------------------------- | ----------- |
| `common`    | `cfg/common.mk`    | lint/fix/clean/update-devenv targets, help     | `node_root` |
| `python`    | `cfg/python.mk`    | Python install/lint/test/build/publish targets |             |
| `node`      | `cfg/node.mk`      | Node install/update targets                    |             |
| `node_root` | `cfg/node_root.mk` | Root-level Node package.json and eslint base   |             |
| `docs`      | `cfg/docs.mk`      | MkDocs build/serve targets                     | `python`    |
| `frontend`  | `cfg/frontend.mk`  | `frontend/` install/lint/test/build            |             |
| `django`    | `cfg/django.mk`    | djlint, collectstatic before the build         | `python`    |
| `docker`    | `cfg/docker.mk`    | Dockerfile lint/fix                            |             |
| `ci`        | `cfg/ci.mk`        | Reusable GitHub Actions workflows and actions  | `python`    |
| `gha_std`   | `cfg/gha_std.mk`   | The standard `ci.yml` composing them           | `ci`        |

A child's `cfg/<project>.mk` that devenv does not ship (codex's `cfg/codex.mk`)
is project-owned; put project-specific targets there, never in a feature `.mk`.

### Key Directories

- `copy/<feature>/` — files copied to child projects on every update: `bin/`
  scripts and `cfg/*.mk`; `copy/ci` and `copy/gha_std` also ship `.github/`
- `merge/<feature>/` — config templates merged into child projects
- `init/<feature>/` — starter files copied once and never over an existing file;
  `X.init.js` installs as `X.js`
- `scripts/` — update, init and merge scripts
- `bin/`, `cfg/` — this repo's own copies (outputs)

### Scripts

Each entry point carries PEP 723 inline metadata, so `uv run scripts/<name>.py`
runs it in its own environment. `tests/test_script_metadata.py` requires every
third-party import (including through sibling modules) to be declared. Sibling
imports carry `# ty: ignore[unresolved-import]` because ty checks a PEP 723
script without its directory on the path.

- `update_devenv.py` — `make update-devenv`: deletes retired files, merges
  dotfiles, copies feature files, runs the three config mergers in process
  through their CLI `main(argv)`, formats the merged files, writes
  `.devenv-version` and prints NEWS since the previous stamp
- `add_features.py` — copies feature files and adds the Makefile includes;
  `--init` and `--convert` also install `init/` starters
- `init-project.sh`, `convert-project.sh` — thin wrappers around
  `add_features.py` and a first `make update-devenv`
- `merge_dotfiles.py` — merges ignore files and rc files based on active
  `DEVENV_*` flags
- `merge_package_json.py` — deep-merges `package.json` with semver resolution
- `merge_toml.py` — merges `pyproject.toml` into the project's own document
- `merge_yaml.py` — round-trip (ruamel.yaml) merge of `mkdocs.yml`,
  `.readthedocs.yaml` and `compose.yaml`
- `copy_files.py` — the copy step; `_makefiles.py` — include editing and mbake

In every merger the project's file is passed last and its values win.

### Retirement

Merges only add, so retiring something devenv used to ship needs an entry.
`update-devenv` then removes it from each child repo:

- `remove_files.txt` — files to delete
- `remove_node_packages.txt` — node packages to drop from every dependency
  section of `package.json`
- `remove_dotfile_lines.txt` — lines to drop from every merged dotfile
- `merge/<feature>/<stem>.remove<ext>` — values to drop from what
  `merge/<feature>/<stem><ext>` merges, same format, same key path, such as
  `merge/python/pyproject-template.remove.toml` (`tool.codespell.skip`) and
  `merge/node_root/package.remove.json` (`prettier.plugins`). An emptied table
  or object is removed.

The three `.txt` lists skip blank and `#` lines, and `# since X.Y.Z` marks the
entries below it. A child stamped with that version or later skips them. When
adding an entry, bump `project.version` in `pyproject.toml`, add a `NEWS.md`
section and file the entry under `# since <new version>`.

An ignore-file merge also drops each pattern that another pattern in the same
file covers, read in that file's syntax: `dist/` beside `dist` in a
`.gitignore`, `node_modules` beside `**/node_modules` in a `.dockerignore`.
Broadening a dotfile pattern therefore needs no retirement entry. A file with a
`!` line is left whole.

### Makefile Conventions

- Uses double-colon (`::`) rules to allow multiple definitions of the same
  target; recipes run in include order
- `OVERRIDE_BUILD` / `OVERRIDE_PUBLISH` (any non-empty value) are read when
  `python.mk` is parsed, so they must be set above the includes
- mbake strips the final newline of every `.mk`; `help.mk` reads them with
  `awk 1` for that reason
- `mbake validate` runs each `.mk` with `make -n`, so a file whose first target
  would recurse or need files has a dummy `all:: ;` first
- Convert keeps the old Makefile and eslint.config.js as `Makefile.orig.mk` and
  `eslint.config.orig.js`

### Tests

- `tests/test_pipeline.py` runs the whole update twice on scratch children for
  several feature sets with bun, bunx and git stubbed; the second run must
  change nothing
- Shell script tests run under both the bash on PATH and `/bin/bash` 3.2
  (`tests/conftest.py`); every `copy/*/bin` script must work on bash 3.2
