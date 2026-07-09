.PHONY: help install sync test test-api test-core lint typecheck run seed clean

help:
	@echo "KnicksIQ Makefile"
	@echo ""
	@echo "  make install   - install all workspace deps via uv"
	@echo "  make sync      - uv sync all packages"
	@echo "  make test      - run all tests"
	@echo "  make test-api  - run only api tests"
	@echo "  make test-core - run only basketball-core tests"
	@echo "  make lint      - ruff check"
	@echo "  make typecheck - pyright"
	@echo "  make run       - run the API server locally"
	@echo "  make seed      - load seed data into the local DB"
	@echo "  make clean     - remove caches and build artifacts"

install:
	uv sync --all-packages

sync:
	uv sync --all-packages

test:
	uv run pytest

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
