# This repo's own recipes, included by the Makefile. The repo owns this file; a standard
# upgrade never changes it. The Makefile's `make <name>` runs `project-<name>` here.
# A placeholder that passes says so; a placeholder for something that ships fails.

.PHONY: project-build project-test project-lint project-ci validate live-loop

PYTEST = uvx --python 3.12 --from 'pytest>=8,<9' --with 'pyyaml>=6,<7' --with 'fastapi>=0.110,<1' pytest -q --import-mode=importlib -p no:cacheprovider --rootdir tests

project-build:
	@echo "nothing to build: the plugin ships as source (project.mk)"

# Unit tests and live tests against a real `annotary serve` (the pinned release binary, downloaded
# once and checked against its pinned SHA-256; ANNOTARY_HERMES_DEV_BINARY overrides it).
project-test:
	$(PYTEST) tests
	node --import ./tests/desktop/register.mjs --test tests/desktop/*.test.mjs

project-lint:
	@uv run --python 3.12 --no-project python -m compileall -q __init__.py annotary_hermes dashboard scripts/project tests
	@python3 scripts/project/check_desktop_page.py
	@python3 scripts/project/validate_package.py

validate: ## Run Hermes's plugin validator on the package (needs Hermes)
	@python3 scripts/project/validate_package.py

PROFILE ?= coder
live-loop: ## One live share, Send back, push, reply, resolve loop on a real Hermes (PROFILE=, MODEL=)
	@python3 scripts/project/live_loop.py --profile $(PROFILE) $(if $(MODEL),--model $(MODEL))

# What CI runs besides the standard lint.
project-ci: project-lint project-test
