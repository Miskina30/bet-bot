# Academic Edge - developer entry points.
#
# The LOCAL profile needs no Docker, no Postgres, no Redis and no API keys:
# SQLite + a filesystem raw archive + labelled fixtures. The PRODUCTION-shaped
# profile is `make up` (docker compose) with Postgres 16, Redis and MinIO.
#
# Windows note: every target also has an equivalent in scripts/run_local.ps1.

PY ?= python
PIP ?= $(PY) -m pip
VENV ?= .venv
VENV_PY := $(VENV)/bin/python
ifeq ($(OS),Windows_NT)
	VENV_PY := $(VENV)/Scripts/python.exe
endif

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test test-fast migrate seed api worker demo up down logs doctor clean clean-all

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install runtime + dev dependencies
	$(PY) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -e ".[dev]"

lint: ## Ruff lint + format check
	$(VENV_PY) -m ruff check .
	$(VENV_PY) -m ruff format --check .

format: ## Auto-fix lint issues and format
	$(VENV_PY) -m ruff check --fix .
	$(VENV_PY) -m ruff format .

typecheck: ## mypy (strict on packages, api, worker)
	$(VENV_PY) -m mypy

test: ## Full test suite
	$(VENV_PY) -m pytest -q

test-fast: ## Unit + property + golden tests only (no API/DB)
	$(VENV_PY) -m pytest -q tests/unit tests/property tests/golden

migrate: ## Apply database migrations
	$(VENV_PY) -m alembic upgrade head

seed: ## Bootstrap the labelled fixture demo dataset (no keys, no network)
	$(VENV_PY) -m academic_edge_worker.cli seed

api: ## Run the API locally (keyless profile)
	$(VENV_PY) -m uvicorn academic_edge_api.main:app --reload --host 127.0.0.1 --port 8000

worker: ## Run the local scheduler (APScheduler; never used in production)
	$(VENV_PY) -m academic_edge_worker.cli run-schedule

demo: migrate seed ## Migrate, seed fixtures, print the opportunity board
	$(VENV_PY) -m academic_edge_worker.cli opportunities
	@echo "Now run: make api    (then open http://127.0.0.1:8000/docs)"

up: ## Start the production-shaped stack with docker compose
	docker compose up --build -d

down: ## Stop the compose stack
	docker compose down

logs: ## Tail compose logs
	docker compose logs -f --tail=200

doctor: ## Diagnose configuration, policy gates and connectivity
	$(VENV_PY) -m academic_edge_worker.cli doctor

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov build dist
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

clean-all: clean ## Also delete local data (SQLite db + raw archive). Destructive.
	rm -rf .data