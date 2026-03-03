.PHONY: fix
## Fix lint errors
## @category Fix
fix::
	uv run mbake format cfg/**/*.mk

.PHONY: lint
## Lint
## @category Lint
lint::
	uv run mbake validate cfg/**/*.mk