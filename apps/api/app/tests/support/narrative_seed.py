"""A validated active release for private narrative calculation cases."""

from __future__ import annotations

import pytest
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.document import Document
from app.models.game import Game
from sqlalchemy import update


@pytest.fixture
async def active_seed_release(client):
    """Pin seeded games and documents to one validated active release."""
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
