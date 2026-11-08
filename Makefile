# Rendered from the repo-standard template; never edited in this repo. The project's own
# recipes live in project.mk: each target here calls the project-<name> target there.
SHELL := /bin/bash -o pipefail
.DEFAULT_GOAL := help
BUMP ?= patch
# Every inner make in a recipe is $(SUBMAKE), never $(MAKE) by name: make runs a recipe line that
# names $(MAKE) even under -n, -t or -q, so `make -n testflight` would upload.
SUBMAKE = $(MAKE) --no-print-directory

include project.mk

.PHONY: help build test lint ci standard-lint

help: ## List the commands
	@grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | sort -u | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

build: project-build ## Build the product (no tests)

test: project-test ## Run the unit tests

lint: standard-lint project-lint ## Run every lint check; fails on findings

ci: standard-lint project-ci ## What the CI job runs (no iOS parts)

standard-lint: ## Check the repo against the standard's file rules, its always-loaded budget, and for British spellings on changed lines
	@python3 scripts/standard/lint.py
	@python3 scripts/standard/always_loaded.py
	@python3 scripts/standard/en_us.py
