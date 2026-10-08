.PHONY: fix
## Fix lint errors
## @category Fix
fix::
	uvx mbake@latest format copy/*/cfg/*.mk

.PHONY: lint
## Lint
## @category Lint
lint::
	uvx mbake@latest validate copy/*/cfg/*.mk