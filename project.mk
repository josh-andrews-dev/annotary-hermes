# This repo's own recipes, included by the Makefile. The repo owns this file; a standard
# upgrade never changes it. The Makefile's `make <name>` runs `project-<name>` here.
# A placeholder that passes says so; a placeholder for something that ships fails.

.PHONY: project-build project-test project-lint project-ci

project-build:
	@echo "nothing to build yet (project.mk)"

project-test:
	@echo "no tests yet (project.mk)"

project-lint:
	@echo "no project lint yet (project.mk)"

# What CI runs besides the standard lint. 
project-ci: project-lint project-test
