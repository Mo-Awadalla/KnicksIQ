.PHONY: help install hooks sync test test-backend test-evaluation test-api test-core lint typecheck run seed clean

help:
	@echo "KnicksIQ Makefile"
	@echo ""
	@echo "  make install   - install all workspace deps via uv"
	@echo "  make hooks     - enable staged-file token limit hook (Git + Python 3.10+)"
	@echo "  make sync      - uv sync all packages"
	@echo "  make test      - run backend workflows and provider-free evaluation CLI scenarios"
	@echo "  make test-api  - run only api tests"
	@echo "  make test-core - run only basketball-core tests"
	@echo "  make lint      - ruff check"
	@echo "  make typecheck - pyright"
	@echo "  make run       - run the API server locally"
	@echo "  make seed      - load seed data into the local DB"
	@echo "  make clean     - remove caches and build artifacts"

install: hooks
	uv sync --all-packages

hooks:
	git config --local core.hooksPath .githooks

sync:
	uv sync --all-packages

test: test-backend test-evaluation

test-backend:
	uv run pytest apps packages tools/report_audit --maxfail=1

test-evaluation:
	uv run --package knicksiq-api python tools/release/eval_scenarios.py

test-api:
	uv run pytest apps/api/app/tests/

test-core:
	uv run pytest packages/basketball-core/tests/

lint:
	uv run ruff check apps/ packages/

typecheck:
	uv run pyright apps/ packages/

run:
	uv run --package knicksiq-api uvicorn app.main:app --reload --port 8000

seed:
	uv run --package knicksiq-api python -c "from app.core.seed_loader import seed_all; from app.core.db import AsyncSessionLocal; import asyncio; asyncio.run(seed_all(AsyncSessionLocal()))"

clean:
	rm -rf .venv **/__pycache__ **/.pytest_cache **/.ruff_cache **/dist **/*.egg-info .uv-cache
