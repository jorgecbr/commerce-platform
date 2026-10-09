# Single entry point for every common task.
# `make` on its own runs the full quality gate, exactly like CI does.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := check
.SILENT:
MAKEFLAGS += --no-print-directory

SERVICE := orders-service
# `--directory` runs the command from inside the service folder, because mypy's
# `files` setting and the coverage paths are relative to it.
PY := uv run --directory $(SERVICE)

# -------------------------------------------------------------------------
# Quality gate
# -------------------------------------------------------------------------
.PHONY: check lint format typecheck deps test coverage

check: lint typecheck deps test ## Run every quality gate (same as CI)

lint: ## ruff lint + format check
	$(PY) ruff check .
	$(PY) ruff format --check .

format: ## ruff autofix + format
	$(PY) ruff check --fix .
	$(PY) ruff format .

typecheck: ## mypy in strict mode
	$(PY) mypy

deps: ## find declared-but-unused dependencies
	$(PY) deptry .

test: ## unit + smoke tests (no Docker required)
	$(PY) pytest

coverage: ## tests with a coverage report
	$(PY) pytest --cov=app --cov-report=term-missing

# -------------------------------------------------------------------------
# App
# -------------------------------------------------------------------------
.PHONY: run install sync

sync: ## install dependencies
	uv sync --project $(SERVICE) --all-groups

run: ## start the API with reload
	cd $(SERVICE) && uv run uvicorn app.main:app --reload --port 8000

# -------------------------------------------------------------------------
# Housekeeping
# -------------------------------------------------------------------------
.PHONY: clean help

clean: ## remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(SERVICE)/.pytest_cache $(SERVICE)/.ruff_cache $(SERVICE)/.mypy_cache
	rm -rf $(SERVICE)/htmlcov $(SERVICE)/.coverage

help: ## list available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'