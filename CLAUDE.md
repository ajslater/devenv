# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## What This Repo Is

A **boilerplate parent configuration system** that houses generic configs and
scripts for managing development environments. It sits as a sibling directory
(`../devenv`) to child projects that reference it. It non-destructively merges
parent configs into child projects via feature-flag-driven scripts.

This repo dogfoods it's own configuration system which is documented for Claude
in @\~/.claude/rules/python-devenv.md

## Common Commands

Refer to @\~/.claude/python-devenv.md

## Architecture

### Feature-Flag System

The project is organized around `DEVENV_<FEATURE>` flags set in child project
Makefiles. Each feature maps to a cfg makefile:

| Flag                                                             | Config             | Purpose                                |
| ---------------------------------------------------------------- | ------------------ | -------------------------------------- |
| `DEVENV_COMMON`                                                  | `cfg/common.mk`    | Base lint/fix/clean/install targets    |
| `DEVENV_PYTHON`                                                  | `cfg/python.mk`    | Python install/lint/test/build targets |
| `DEVENV_NODE`                                                    | `cfg/node.mk`      | Node install/update targets            |
| `DEVENV_NODE_ROOT`                                               | `cfg/node_root.mk` | Root-level Node package.json           |
| `DEVENV_DOCS`                                                    | `cfg/docs.mk`      | MkDocs build/serve targets             |
| `DEVENV_CI`, `DEVENV_DJANGO`, `DEVENV_DOCKER`, `DEVENV_FRONTEND` | `cfg/<feature>/`   | Optional features                      |

### Key Directories

- `cfg/` — Makefile modules included by child projects; the `cfg/help.mk`
  provides a color-coded help system
- `copy/` - Config files & scripts that are copied entirely to child projects.
- `merge/` — Config templates merged into child projects (`common/`, `python/`,
  `node_root/`, `docs/`, `docker/`)
- `init/` — One-time starter files copied when initializing a new project
- `scripts/` — Update and initialization scripts
- `bin/` — Development helper scripts

### Merge Scripts

The update system in `scripts/` handles non-destructive merging:

- `merge-dotfiles.sh` — Merges ignore files and rc files based on active
  `DEVENV_*` flags
- `merge_package_json.py` — Deep-merges `package.json` with intelligent semver
  resolution
- `merge_toml.py` — Merges TOML configs (used for `pyproject.toml`)
- `merge_yaml.py` — Merges YAML configs (used for `mkdocs.yml`)
- `update-devenv.sh` — Main entry point: runs delete, merge, and copy operations

### Makefile Conventions

- Uses double-colon (`::`) rules to allow multiple definitions of the same
  target
- Targets can be overridden with `OVERRIDE_BUILD=1` / `OVERRIDE_PUBLISH=1`
- Old Makefile and eslint.config.js are saved with `~` suffix as reference

### Linting & Testing

Refer to @\~/.claude/python-devenv.md
