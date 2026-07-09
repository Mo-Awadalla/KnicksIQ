"""Async database session factory.

When `test_mode` is True (or the engine is SQLite), we disable the
connection pool to avoid the "connection pool is closed" error that
arises when sharing an in-memory DB across event-loop boundaries in
tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

_engine_kwargs: dict = {"echo": _settings.db_echo}
if _settings.test_mode or _settings.effective_db_url.startswith("sqlite"):
    # SQLite in-memory requires a single shared connection;
    # disable pooling to keep things simple for tests.
    _engine_kwargs["poolclass"] = None  # type: ignore[arg-type]

engine = create_async_engine(_settings.effective_db_url, **_engine_kwargs)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
