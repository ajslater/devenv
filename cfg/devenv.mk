.PHONY: fix
## Fix lint errors
## @category Fix
fix::
	uv run mbake format root/*/cfg/*.mk

.PHONY: lint
## Lint
## @category Lint
lint::
	uv run mbake validate root/*/cfg/*.mk