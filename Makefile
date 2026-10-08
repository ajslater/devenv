SHELL := /usr/bin/env bash
# devenv is its own source, wherever it is checked out.
DEVENV_SRC := $(CURDIR)

include cfg/devenv.mk
# include cfg/django.mk
# include cfg/frontend.mk
include cfg/python.mk
# include cfg/ci.mk
# include cfg/docker.mk
include cfg/node.mk
include cfg/node_root.mk
include cfg/common.mk
include cfg/help.mk

.PHONY: all