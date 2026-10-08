# devenv News

## v0.2.0

- Breaking Changes
    - Features declare what they need and update-devenv refuses an incomplete
      set: django needs frontend and python; gha_std needs ci; ci and docs need
      python; common needs python and node_root.
    - `scripts/add_makefiles.py` is now `scripts/add_features.py`.
    - django's `prod-server` target moved to codex, the one project it ran.
- Features
    - update-devenv stamps `.devenv-version`, prints devenv news since the last
      update, and no longer deletes a file retired before that.
    - `make update-devenv UPDATE_DEVENV_FLAGS=--no-update-deps` skips
      `bun update`.
- Fixes
    - init and convert keep existing files, and add the includes for the
      features they are given.
