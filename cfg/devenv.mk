.PHONY: fix
## Fix lint errors
## @category Fix
fix::
	uv run mbake format copy/*/cfg/*.mk

.PHONY: lint
## Lint
## @category Lint
lint::
	uv run mbake validate copy/*/cfg/*.mk