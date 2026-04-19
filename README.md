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
