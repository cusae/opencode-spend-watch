PYTHON ?= python3
RUFF ?= ruff
MYPY ?= mypy
COVERAGE ?= coverage
BATS ?= bats
SHELLCHECK ?= shellcheck
ACTIONLINT ?= actionlint
YAMLLINT ?= $(PYTHON) -m yamllint
MARKDOWNLINT ?= markdownlint-cli2
GIT_CLIFF ?= git-cliff

.DEFAULT_GOAL := help

.PHONY: help setup hooks lint format format-check types test coverage shell docs changelog check clean

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install the development tools
	$(PYTHON) -m pip install -r requirements-dev.txt

hooks: ## Point git at the repository hooks
	git config core.hooksPath .githooks

lint: ## Lint Python, shell and YAML
	$(RUFF) check .
	$(SHELLCHECK) install.sh .githooks/commit-msg
	$(YAMLLINT) -c .yamllint.yml .github

format: ## Format the Python sources
	$(RUFF) format .

format-check: ## Verify formatting without changing files
	$(RUFF) format --check .

types: ## Type-check watch.py
	$(MYPY) watch.py notify.py providers.py

test: ## Run the Python tests
	$(PYTHON) -m py_compile watch.py
	$(PYTHON) -m unittest discover -s test/python -t . -v

coverage: ## Run the Python tests with the coverage gate
	$(COVERAGE) run -m unittest discover -s test/python -t .
	$(COVERAGE) report

shell: ## Run the bats and shellcheck suites
	$(BATS) test/shell

changelog: ## Regenerate CHANGELOG.md from Conventional Commits
	$(GIT_CLIFF) --output CHANGELOG.md

docs: ## Lint Markdown, YAML, and the GitHub workflows
	$(MARKDOWNLINT)
	$(YAMLLINT) -c .yamllint.yml .github
	$(ACTIONLINT)

check: lint format-check types coverage shell docs ## Run every check

clean: ## Remove caches and reports
	rm -rf __pycache__ test/__pycache__ test/python/__pycache__ \
		.ruff_cache .mypy_cache .coverage htmlcov coverage.xml
