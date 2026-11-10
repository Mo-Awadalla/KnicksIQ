"""Shared cache isolation for public analyst endpoint cases."""

from __future__ import annotations

import pytest
from app.api import analysis
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.document import Document
from app.models.game import Game
from sqlalchemy import update


@pytest.fixture(autouse=True)
def isolate_response_cache(monkeypatch):
    async def cache_miss(_key):
        return None

    async def discard_cache_write(_key, _value):
        return None

    monkeypatch.setattr(analysis, "get_cached_answer", cache_miss)
    monkeypatch.setattr(analysis, "set_cached_answer", discard_cache_write)


@pytest.fixture
async def active_seed_release(client):
    """Give the existing public-API seed a validated release, without changing other tests."""
    async with AsyncSessionLocal() as db:
        release = DatasetRelease(
            version="narrative-seed-test",
            season="2025-26",
            source="test",
            manifest_sha256="a" * 64,
            validation_passed=True,
            status="active",
        )
        db.add(release)
        await db.flush()
        await db.execute(update(Game).values(release_id=release.id))
        await db.execute(update(Document).values(release_id=release.id))
        await db.commit()
    return client


async def _true() -> bool:
    return True
