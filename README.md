# AJ's Development Environment

This repo houses generic boilerplate parent configurations and scripts for
managing my development environment. The scripts non-destructively merge these
parent configurations with child projects that use it, and can be re-run at any
time.

This replaces my old boilerplate repo.

## Setup

This repo is intended to sit as a sibling directory to projects that reference
it. The scripts could be expanded to find the files online but that doesn't
currently seem necessary.

The scripts need [uv](https://docs.astral.sh/uv/) and, for the node features,
[bun](https://bun.sh). Each devenv script declares its own Python dependencies
inline (PEP 723), so `uv run` gives it its own environment and nothing has to be
installed into the project first.

### Initializing a new project

```sh
mkdir new_project
cd new_project
../devenv/scripts/init-project.sh [FEATURE ...]
```

This creates a git repo if there is none, installs starter files from `init/`,
copies the feature files, makes the `Makefile` include each feature, and runs a
first `make update-devenv`. It gets the default features
(`python node node_root common`) plus any listed.

### Converting a project that used my old boilerplate scripts

```sh
cd old_project
../devenv/scripts/convert-project.sh [FEATURE ...]
```

Like `init-project.sh`, but first keeps the old `Makefile` and
`eslint.config.js` as `Makefile.orig.mk` and `eslint.config.orig.js`. Copy
project-specific sections from them into the new files. Running it again keeps
the first `*.orig.*` files.

Neither script replaces a file the project already has.

### Adding features

```sh
uv run ../devenv/scripts/add_features.py docker docs
make update-devenv
```

This copies the features' files and adds `include cfg/<feature>.mk` lines to the
`Makefile` in the right order, uncommenting them where they exist. Run it with
`-h` for the features.

## Features

Each feature is a `DEVENV_<FEATURE>` flag, set by including `cfg/<feature>.mk`
in the project `Makefile`. A feature that needs another refuses to run without
it: `add_features.py` and `update-devenv` stop with a one-line message.

| Feature     | Adds                                                    | Requires    |
| ----------- | ------------------------------------------------------- | ----------- |
| `common`    | lint, fix, clean, `update-devenv`, help, ignore files   | `node_root` |
| `python`    | uv install, lint, typecheck, test, build and publish    |             |
| `node`      | bun install and update, eslint_d                        |             |
| `node_root` | the root `package.json` and the base eslint config      |             |
| `docs`      | mkdocs build and serve                                  | `python`    |
| `frontend`  | install, lint, test and build in `frontend/`            |             |
| `django`    | djlint, `bin/pm`, collectstatic before the python build | `python`    |
| `docker`    | hadolint and dockerfmt over every Dockerfile            |             |
| `ci`        | the GitHub Actions building blocks below                | `python`    |
| `gha_std`   | the standard `ci.yml` that uses them                    | `ci`        |

The order of the includes matters, and `add_features.py` keeps it: `OVERRIDE_*`
is read when `python.mk` is parsed, and `::` recipes run in include order, so
django's collectstatic runs before the python build. collectstatic first runs
`build-frontend`, which does nothing unless the frontend feature or the
project's own `cfg/<project>.mk` defines it.

## Use

Everything is done via the makefile.

```sh
make
```

for help.

### Updating the development environment

```sh
make update-devenv
```

This deletes retired files, merges the dotfiles and config files, copies the
feature files, formats what it merged and stamps the project with devenv's
version in `.devenv-version`. Commit that file. On the next update devenv prints
its news since that version.

It also runs `bun update`, which bumps every node dependency. To keep versions
as they are:

```sh
make update-devenv UPDATE_DEVENV_FLAGS=--no-update-deps
```

Merging only adds:

- **Values the project has win.** Template keys it lacks are added. In
  `pyproject.toml` and the YAML files the project's comments, key order, tags,
  anchors and formatting stay too.
- **Arrays and lists** in `pyproject.toml` and the YAML files keep the project's
  order and gain the template's missing items. In `package.json` they are
  sorted, de-duplicated unions, except prettier's `overrides`, which apply in
  order: the template's come first. In `pyproject.toml`, only
  `tool.codespell.skip`, `tool.codespell.ignore-words-list`,
  `tool.codespell.builtin` and `tool.radon.exclude` are comma lists; every other
  string is a plain value.
- **package.json scripts** keep the project's `&&` steps and gain the template's
  missing ones. A command the template changes reaches projects only if the old
  one is retired (below).
- **Dependency specs** keep the higher floor. A bare `>=` beats a bounded range,
  and a protocol spec such as `workspace:` or `catalog:` is kept as written.
  `merge_package_json.py --help` has the details.
- **Ignore files** are sorted bytewise (`LC_ALL=C`) with negations last, and a
  pattern that another one already covers is dropped.

### Shell scripts

`make fix-sh` and `make lint-sh` run shellharden, shfmt and (lint only)
shellcheck over every `*.sh` file and every extensionless file with a sh or bash
shebang, such as `bin/pm`. Every script in `bin/` runs under macOS's stock bash
3.2.

A lint or fix tool that is not installed is skipped with
`skipped: <tool> not installed (brew install <tool>)` on stderr, so a missing
tool is visible rather than a silent pass.

To skip some scripts, list patterns in a `.shellignore` file at the project
root, one per line:

- Blank lines and lines starting with `#` are ignored.
- A pattern without a `/` matches a file or directory name at any depth, like
  `node_modules` or `*_old.sh`.
- A pattern with a `/` is anchored to the project root. `scripts/vendor` skips
  `./scripts/vendor` but not `./lib/scripts/vendor`. A leading `./` or `/` and a
  trailing `/` are stripped.
- `*`, `?` and `[...]` are glob characters. In a pattern with a `/`, `*` also
  matches `/`, so `scripts/*_old.sh` skips `scripts/sub/x_old.sh` too.
- A leading `!` re-includes what the other patterns skip. The order of lines
  does not matter.

Skipped directories are never searched. As with `.gitignore`, a file inside a
skipped directory cannot be re-included: `!.github/scripts` does nothing while
`.github` is skipped. Re-include the directory itself instead.

devenv seeds `.shellignore` with `.*` (hidden files and directories) and
`node_modules`, and `make update-devenv` adds those two lines back if they are
removed. To lint a hidden directory such as `.github`, keep them and add a
negation:

```text
.*
!.github
node_modules
```

The docker and django scripts find Dockerfiles and templates with the same
rules, through `bin/find-files.sh`.

### Other scripts

These are copied but run by hand:

- `uv run bin/hub_prune_stale.py NAMESPACE/REPO [--execute]` (docker) deletes
  stale Docker Hub tags.
- `bin/docker-tag-latest.sh` and `bin/docker-compose-exit.sh` (docker) say how
  to run them in their first lines.
- `bin/cleanup-pypi-alpha.sh` (python) deletes PyPI pre-releases.
- `make uml` (python) writes class diagrams to `test-results/uml/`.

## Customization

### Overriding build and publish

Makefiles use `target::` double colons so every included target of the same name
runs. To add a step to the build, define another `build::` in the project
`Makefile` or its own `cfg/<project>.mk`. With django or frontend that is the
only way, since they add to `build::` themselves.

To replace python's `build` or `publish` entirely, set `OVERRIDE_BUILD` or
`OVERRIDE_PUBLISH` to any non-empty value **above** the includes, because
`python.mk` reads them when it is parsed, and define your own target. The
starter `Makefile` has them commented out in the right place.

### Project makefiles

A `cfg/<project>.mk` that devenv does not ship, such as codex's `cfg/codex.mk`,
belongs to the project. devenv never copies over it. Include it before the
feature makefiles.

## Structure

The sources are:

- `copy/<feature>/` Scripts and configs copied wholesale into projects, such as
  `bin/` scripts and `cfg/*.mk`. A project's copies are replaced on every
  update, so edit them here.
- `merge/<feature>/` Configs merged into projects: ignore and rc dotfiles,
  `package.json`, `pyproject-template.toml`, `mkdocs.yml`, `.readthedocs.yaml`
  and `compose.yaml`. Any enabled feature may add to a file another feature
  owns; django adds djlint to `pyproject.toml`.
- `init/<feature>/` Starter files copied once into new projects. A file named
  like `eslint.config.init.js` is installed as `eslint.config.js`.
- `scripts/` The update, init and merge machinery.
- The retirement lists below.

This repo dogfoods itself: its root `bin/`, `cfg/` (except `cfg/devenv.mk`),
dotfiles, `package.json` and `pyproject.toml` are update output.

## Retiring things

Merges only add, so removing something devenv used to ship needs a retirement
entry. `make update-devenv` then removes it from each project:

- `remove_files.txt`: files to delete. Each deletion is printed.
- `remove_node_packages.txt`: node packages to drop from every dependency
  section of `package.json`.
- `remove_dotfile_lines.txt`: lines to drop from every merged dotfile.
- `merge/<feature>/<stem>.remove<ext>`: values to drop from what
  `merge/<feature>/<stem><ext>` merges, in the same format and at the same key
  paths. A list there names the values to drop from the array, comma list, YAML
  list or `&&` script at that path; a table or object emptied this way is
  removed. Examples: `merge/python/pyproject-template.remove.toml` and
  `merge/node_root/package.remove.json`.

In the three `.txt` lists, blank lines and `#` lines are skipped, and a
`# since X.Y.Z` line marks the entries below it as retired in devenv X.Y.Z. A
project stamped with that version or later already had them applied, so they are
skipped there, and the project may keep a file of its own by a retired name.
When you add an entry, bump devenv's version in `pyproject.toml`, add a
`NEWS.md` section, and put the entry under a `# since` line for the new version.
Once every project is stamped past a version, the entries up to it can be
deleted.

## Developing devenv

```sh
make install
make fix lint test
```

devenv's own `.github/workflows/ci.yml` runs lint and the tests and then checks
that `make update-devenv UPDATE_DEVENV_FLAGS=--no-update-deps` changes nothing
in the repo, so the dogfooded outputs cannot drift from their sources. It is not
a feature, so no project gets it. `tests/test_pipeline.py` runs the whole update
twice on scratch projects and requires the second run to change nothing.

## GitHub Actions

The `ci` feature copies these CI building blocks into a project. They are
overwritten on every update, so edit them here, not in the project. It needs the
`python` feature, a Dockerfile whose CI stage has `WORKDIR /app` (see
`merge/ci/compose.yaml`), and `jq`, `gh` and `actionlint` on the runner.

- `.github/workflows/devenv-check.yml`: a reusable workflow with these jobs:
    - A gate. It runs `bin/release-tag.sh preflight`. On a main push it reuses
      the `python-dist` of an earlier run that passed on the same git tree. Any
      failure to read the tree, list artifacts, parse the list or download the
      dist prints a warning and falls back to a full lint, test and build.
    - One job that builds the CI image with the registry cache and pushes it by
      digest to `ghcr.io/<repo>-ci`. A companion job prunes old untagged images.
    - A fail-fast matrix of lint, test and build, where every combo pulls that
      image.
    - The `Lint, Test & Build Dist` aggregator, which is the required check.

    Its inputs are `matrix` (the check combos), `ci-target` (the Dockerfile
    stage), `container`, `runner`, `release-preflight` and `retention-days`. Its
    outputs `deploy`, `release`, `version` and `final` are the only trigger
    logic that later jobs need; `dist_found`, `source_run_id` and `tree`
    describe a reused dist.

    Projects that cannot run in a Linux container (wpls needs macOS) pass
    `container: false` and `runner: macos-latest`. Then no image is built, and
    each combo runs `make install` and its targets directly on that runner.

    A pull request into develop runs the checks only from `pre-release` or from
    a version branch, `v` and a digit such as `v1.2.3`. Any other pull request
    into develop skips the gate, and GitHub counts the skipped required check as
    passing.

    Job timeouts are fixed: gate 10 minutes, image 45, prune 10, each check
    combo 30 and the aggregator 5.

- `.github/workflows/devenv-release.yml`: a reusable workflow that tags the
  release, creates the GitHub Release from NEWS.md and merges main into develop.
- `.github/actions/devenv-ci-container`: pulls the CI image by digest and starts
  the CI container.
- `.github/actions/devenv-pypi`: publishes `python-dist` to PyPI. Given a
  `token`, it uploads with that API token. Without one, it uses PyPI trusted
  publishing: GitHub Actions gives the job a short-lived identity token, and
  PyPI exchanges it for an upload token. For that, the job must grant
  `id-token: write` and must be in the project's own `ci.yml`, because PyPI
  refuses trusted publishing from inside a reusable workflow. Register `ci.yml`
  as the project's GitHub publisher on PyPI.

Third-party actions are pinned by commit SHA with the release as a comment
(`uses: actions/checkout@<sha> # v6.1.0`). Bump them here, and change every use
of an action together; a test requires one pin per action.

The `gha_std` feature, which also needs `ci`, copies in the standard `ci.yml`.
It runs `devenv-check`, then publishes to PyPI, then runs `devenv-release`. It
passes `secrets.PYPI_TOKEN` to `devenv-pypi`, so deleting that secret switches
the project to trusted publishing. Its required check is
`CI / Lint, Test & Build Dist`. A newer push cancels a pull request's run, but a
main run that has started always finishes, so a release is never cut between the
PyPI upload and the tag. A project that needs its own jobs drops `gha_std` and
owns its `ci.yml`, composing the same blocks. To add your own jobs:

1. Your jobs `needs: ci` and run under
   `!cancelled() && needs.ci.result == 'success' && needs.ci.outputs.deploy == 'true'`.
   Never write your own event logic.
2. Download the dist with `name: python-dist`. It exists whether it was built or
   reused.
3. The release job's `needs` lists every deploy job, and each must be
   `== 'success'`. Allow `'skipped'` only for jobs that are legitimately
   optional.
4. The job that runs `devenv-pypi` grants `id-token: write`.

The repository variable `RELEASE_AUTOMATION=off` turns off the preflight and the
release job.
