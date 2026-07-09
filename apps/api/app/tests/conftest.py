"""Shared pytest fixtures.

Tests use SQLite in-memory + the FastAPI TestClient. This is the
default — Postgres is not required for any test in this repo.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Force test mode before importing any app code so config picks it up.
# `.env` sets TEST_MODE=false for dev, so setdefault is not strong enough here.
os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"
os.environ["DEBUG"] = "true"

import pytest
from app.core.db import engine
from app.core.seed_loader import seed_all
from app.main import create_app
from app.models import Base
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="function")
async def db_session() -> AsyncIterator:
    """Yield a fresh, schema-loaded, seeded DB session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await seed_all(session)
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def client() -> AsyncIterator[AsyncClient]:
    """Yield an httpx AsyncClient bound to the FastAPI app."""
    # Re-create the app per test to reset lifespan state.
    app = create_app()
    async with app.router.lifespan_context(app):
        from app.core.db import AsyncSessionLocal
        from app.core.seed_loader import seed_all

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as session:
            await seed_all(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
