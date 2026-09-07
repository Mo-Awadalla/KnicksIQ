"""A real development server must observe the same release boundary as production."""

from types import SimpleNamespace

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services import releases
from sqlalchemy import update


async def test_real_development_reads_exclude_historical_games(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        release = DatasetRelease(
            version="read-scope",
            season="2025-26",
            source="test",
            manifest_sha256="b" * 64,
            validation_passed=True,
            status="active",
        )
        db.add(release)
        await db.flush()
        await db.execute(update(Game).where(Game.id == 1).values(release_id=release.id))
        await db.commit()
    monkeypatch.setattr(
        releases,
        "get_settings",
        lambda: SimpleNamespace(
            is_production=False,
            test_mode=False,
            require_active_release=True,
        ),
    )
    response = await client.get("/games")
    assert response.status_code == 200
    assert [game["id"] for game in response.json()] == [1]
