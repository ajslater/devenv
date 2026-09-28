# AJ's Development Environment

This repo houses generic boilerplate parent configurations and scripts for
managing my development environment. The scripts non-destructively merge these
parent configuations with child projects that use it.

This replaces my old boilerplate repo

## Setup

This repo is indended to sit as a sibling directory to projects that reference
it. The scripts could be expanded to find the files online but that doesn't
currenty seem neccessary.

### Initializing a new project

```sh
mkdir new_project
cd new_project
../devenv/initialize-project.sh
```

### Converting a project that used my old boilerplate scripts

```sh
cd old_project
../devenv/convert-project.sh
```

### Customization

#### Features

Add features with the `../devenv/add-makefiles.sh` script listed as arguments.
Available and default features are are listed with `-h`

#### Old files

The old Makefile and eslint.config.js are saved for reference. Copy project
unique sections into the new Makefile and eslint.config.js

## Use

Everything is done via the makefile.

```sh
make
```

for help.

### Updating the developent environment

```sh
make update-devenv
```

## Structure

- `bin/` Development environment scripts
- `cfg/` Parent makefile and eslint configurations which to be included by the
- `copy/` Parent scripts & configs that are copied into client projects.
  project's Makefile and eslint config.
- `merge/` Parent configs that are merged by scripts.
- `init/` Initial configuratioin files copied to new projects.

## Modification

Makefiles often use target:: double colons so all included targets with the same
name are run.

If the build target should be replaced entirely set `OVERRIDE_BUILD = 1` in an
included makefile and define a build: target.

## GitHub Actions

The `ci` feature copies these CI building blocks into a project. They are
overwritten on every update, so edit them here, not in the project.

- `.github/workflows/devenv-check.yml`: a reusable workflow with these jobs:
    - A gate. It runs `bin/release-tag.sh preflight`. On a main push it reuses
      the `python-dist` of an earlier run that passed on the same git tree.
    - A fail-fast matrix of lint, test and build in the CI container.
    - The `Lint, Test & Build Dist` aggregator, which is the required check.

    Its outputs (`deploy`, `release`, `version`, `final`) are the only trigger
    logic that later jobs need.

- `.github/workflows/devenv-release.yml`: a reusable workflow that tags the
  release, creates the GitHub Release from NEWS.md and merges main into develop.
- `.github/actions/devenv-ci-container`: builds and starts the CI container.
- `.github/actions/devenv-pypi`: publishes `python-dist` to PyPI.

The `gha_std` feature, which also needs `ci`, copies in the standard `ci.yml`.
It runs `devenv-check`, then publishes to PyPI, then runs `devenv-release`. Its
required check is `CI / Lint, Test & Build Dist`. A project that needs its own
jobs drops `gha_std` and owns its `ci.yml`, composing the same blocks. To add
your own jobs:

1. Your jobs `needs: ci` and run under
   `!cancelled() && needs.ci.result == 'success' && needs.ci.outputs.deploy == 'true'`.
   Never write your own event logic.
2. Download the dist with `name: python-dist`. It exists whether it was built or
   reused.
3. The release job's `needs` lists every deploy job, and each must be
   `== 'success'`. Allow `'skipped'` only for jobs that are legitimately
   optional.

The repository variable `RELEASE_AUTOMATION=off` turns off the preflight and the
release job.
