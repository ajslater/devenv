DEVENV_NODE_ROOT := 1
export DEVENV_NODE_ROOT

.PHONY: install-deps-npm
## Update and install node packages
## @category Install
install-deps-npm:
	npm install

.PHONY: install
## Install
## @category Install
install:: install-deps-npm

.PHONY: update-npm
## Update npm dependencies
## @category Update
update-npm:
	./bin/update-deps-npm.sh

.PHONY: update
## Update dependencies
## @category Update
update:: update-npm

.PHONY: kill-eslint_d
## Kill eslint daemon
## @category Lint
kill-eslint_d:
	bin/kill-eslint_d.sh

## Show version. Use V variable to set version
## @category Update
V :=
.PHONY: version
## Show or set project version for npm
## @category Update
version::
	bin/version-npm.sh $(V)