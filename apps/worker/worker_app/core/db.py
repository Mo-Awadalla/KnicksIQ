"""Async database engine for worker (mirrors API's db.py).

The worker shares the database with the API — both use the same
SQLAlchemy models and the same connection pool. We reuse the API's
`engine` and `AsyncSessionLocal` rather than creating a second one
(this also avoids the SQLite in-memory gotcha where each
`create_async_engine(":memory:")` call yields a fresh database).
"""

from __future__ import annotations

from app.core.db import AsyncSessionLocal, engine  # noqa: F401

__all__ = ["engine", "AsyncSessionLocal"]
