"""Tests for the worker service.

These run the job functions directly (no RQ, no Redis) and assert
that they correctly update the Job table.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

# Force test mode before any app imports.
os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.player import Player  # noqa: E402


@pytest.fixture(scope="function")
async def worker_db() -> AsyncIterator:
    """Yield a fresh DB with the worker's expected schema."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_ingest_games_creates_jobs(worker_db):
    """The ingest_games job should run, update the Job row to 'finished'."""
    from worker_app.jobs.ingest_games import ingest_games

    job_id = "test_job_001"
    async with AsyncSessionLocal() as db:
        # Pre-create a queued job so the worker has something to update.

        job = Job(
            id=job_id,
            job_type="ingest_games",
            status="queued",
            payload_json="{}",
        )
        db.add(job)
        await db.commit()

    # Run the job.
    result = await ingest_games(job_id=job_id, season=None)

    assert "inserted_game_ids" in result
    assert "skipped_nba_game_ids" in result
    assert isinstance(result["inserted_game_ids"], list)

    # The Job row should now be in 'finished' state.
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert row.status == "finished"
        assert row.started_at is not None
        assert row.finished_at is not None
        assert row.worker_name is not None
        assert row.result_json is not None
        assert "inserted_game_ids" in row.result_json


async def test_ingest_game_detail_normalizes_events(worker_db):
    """A single-game ingest should populate the game_events table."""
    from app.core.seed_loader import seed_teams
    from worker_app.jobs.ingest_game_detail import ingest_game_detail
    from worker_app.jobs.ingest_games import ingest_games

    # The ingest_games job requires teams to exist before it inserts games.
    async with AsyncSessionLocal() as db:
        await seed_teams(db)

    # First ingest games so we have a game id to ingest detail for.
    games_job_id = "test_games_setup"
    async with AsyncSessionLocal() as db:
        db.add(Job(id=games_job_id, job_type="ingest_games", status="queued", payload_json="{}"))
        await db.commit()
    games_result = await ingest_games(job_id=games_job_id, season=None)
    assert games_result["inserted_game_ids"], "expected at least one game ingested"

    game_id = games_result["inserted_game_ids"][0]

    # Now ingest the detail (events) for that game.
    detail_job_id = "test_detail_001"
    async with AsyncSessionLocal() as db:
        db.add(
            Job(
                id=detail_job_id,
                job_type="ingest_game_detail",
                status="queued",
                payload_json="{}",
            )
        )
        await db.commit()
    result = await ingest_game_detail(job_id=detail_job_id, game_db_id=game_id)
    assert result["game_id"] == game_id
    assert result["events_ingested"] > 0

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Job).where(Job.id == detail_job_id))).scalar_one()
        assert row.status == "finished"


async def test_player_id_map_creates_missing_players(worker_db):
    from app.core.seed_loader import seed_teams
    from worker_app.jobs.ingest_game_detail import _build_player_id_map

    raw_events = [
        {
            "player_id": 999001,
            "player_name": "Test Guard",
            "team_id": "NYK",
        }
    ]
    async with AsyncSessionLocal() as db:
        await seed_teams(db)
        player_id_map = await _build_player_id_map(db, raw_events)
        assert 999001 in player_id_map
        player = (
            await db.execute(select(Player).where(Player.nba_player_id == 999001))
        ).scalar_one()
        assert player.full_name == "Test Guard"
        assert player.team_id == "NYK"


async def test_ingest_games_handles_unknown_game_id(worker_db):
    """If the game id doesn't exist, the job should fail with a clear error."""
    from worker_app.jobs.ingest_game_detail import ingest_game_detail

    detail_job_id = "test_missing_game"
    async with AsyncSessionLocal() as db:
        db.add(
            Job(
                id=detail_job_id,
                job_type="ingest_game_detail",
                status="queued",
                payload_json="{}",
            )
        )
        await db.commit()

    with pytest.raises(ValueError, match="not found"):
        await ingest_game_detail(job_id=detail_job_id, game_db_id=99999)

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Job).where(Job.id == detail_job_id))).scalar_one()
        assert row.status == "failed"
        assert "not found" in (row.error_message or "")
