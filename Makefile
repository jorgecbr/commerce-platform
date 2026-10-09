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
.PHONY: check lint format typecheck deps test test-unit test-integration coverage

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

test: ## whole suite; integration tests skip themselves if infra is missing
	$(PY) pytest

test-unit: ## domain and application only, never touches the network
	$(PY) pytest tests/domain tests/application tests/test_health.py

test-integration: ## needs PostgreSQL and Redis running
	$(PY) pytest tests/integration

coverage: ## tests with a coverage report
	$(PY) pytest --cov=app --cov-report=term-missing

# -------------------------------------------------------------------------
# App
# -------------------------------------------------------------------------
.PHONY: run sync

sync: ## install dependencies
	uv sync --project $(SERVICE) --all-groups

run: ## start the API with reload
	cd $(SERVICE) && uv run uvicorn app.main:app --reload --port 8000

# -------------------------------------------------------------------------
# Infrastructure
# -------------------------------------------------------------------------
.PHONY: up down migrate revision reset-db

up: ## start PostgreSQL, Redis and Kafka
	docker compose up -d postgres redis kafka
	docker compose ps

down: ## stop everything and drop the volumes
	docker compose down -v

migrate: ## apply migrations
	cd $(SERVICE) && uv run alembic upgrade head

revision: ## autogenerate a migration: make revision msg="add index"
	cd $(SERVICE) && uv run alembic revision --autogenerate -m "$(msg)"

reset-db: ## recreate the database and reapply every migration
	docker compose down -v
	$(MAKE) up
	$(MAKE) migrate

# -------------------------------------------------------------------------
# Housekeeping
# -------------------------------------------------------------------------
.PHONY: clean help

clean: ## remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(SERVICE)/.pytest_cache $(SERVICE)/.ruff_cache $(SERVICE)/.mypy_cache
	rm -rf $(SERVICE)/htmlcov $(SERVICE)/.coverage $(SERVICE)/coverage.xml

help: ## list available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'