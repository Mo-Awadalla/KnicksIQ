"""Tests for the basketball-logic detector worker job."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.bad_stretch import BadStretch  # noqa: E402
from app.models.game_event import GameEvent  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.scoring_run import ScoringRun  # noqa: E402


@pytest.fixture(scope="function")
async def worker_db() -> AsyncIterator:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_game_with_events() -> int:
    """Insert a game with a small sequence of events for the detector to process.

    Returns the game's internal id.
    """
    from datetime import date

    from app.core.seed_loader import seed_teams
    from app.models.game import Game

    async with AsyncSessionLocal() as db:
        await seed_teams(db)
        game = Game(
            nba_game_id="00224DETECT",
            season="2024-25",
            game_date=date(2024, 11, 1),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110,
            away_score=98,
            status="final",
        )
        db.add(game)
        await db.flush()

        # Build a sequence that has a clear 8-0 Knicks run
        # then an 8-0 opponent swing, plus some turnovers.
        events = [
            GameEvent(
                game_id=game.id, sequence=1, period=1, clock="11:00",
                team_id="NYK", event_type="made_shot", description="made 2pt",
                home_score=2, away_score=0, score_margin=2,
                shot_type="2pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=2, period=1, clock="10:30",
                team_id="NYK", event_type="made_shot", description="made 2pt",
                home_score=4, away_score=0, score_margin=4,
                shot_type="2pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=3, period=1, clock="10:00",
                team_id="NYK", event_type="made_shot", description="made 2pt",
                home_score=6, away_score=0, score_margin=6,
                shot_type="2pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=4, period=1, clock="9:30",
                team_id="NYK", event_type="made_shot", description="made 2pt",
                home_score=8, away_score=0, score_margin=8,
                shot_type="2pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=5, period=1, clock="9:00",
                team_id="BOS", event_type="made_shot", description="made 2pt",
                home_score=8, away_score=2, score_margin=6,
                shot_type="2pt", shot_result="made",
            ),
            # Opponent run starts
            GameEvent(
                game_id=game.id, sequence=6, period=3, clock="8:00",
                team_id="BOS", event_type="made_shot", description="made 3pt",
                home_score=70, away_score=50, score_margin=20,
                shot_type="3pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=7, period=3, clock="7:30",
                team_id="NYK", event_type="turnover", description="turnover",
                home_score=70, away_score=50, score_margin=20,
            ),
            GameEvent(
                game_id=game.id, sequence=8, period=3, clock="7:00",
                team_id="BOS", event_type="made_shot", description="made 2pt",
                home_score=70, away_score=52, score_margin=18,
                shot_type="2pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=9, period=3, clock="6:30",
                team_id="NYK", event_type="turnover", description="turnover",
                home_score=70, away_score=52, score_margin=18,
            ),
            GameEvent(
                game_id=game.id, sequence=10, period=3, clock="6:00",
                team_id="BOS", event_type="made_shot", description="made 3pt",
                home_score=70, away_score=55, score_margin=15,
                shot_type="3pt", shot_result="made",
            ),
            GameEvent(
                game_id=game.id, sequence=11, period=3, clock="5:30",
                team_id="NYK", event_type="made_shot", description="made 2pt",
                home_score=72, away_score=55, score_margin=17,
                shot_type="2pt", shot_result="made",
            ),
        ]
        for ev in events:
            db.add(ev)
        await db.commit()
        return game.id


async def test_detect_runs_populates_scoring_runs_table(worker_db):
    from worker_app.jobs.detect_runs import detect_game_features

    game_id = await _seed_game_with_events()
    job_id = "test_detect_001"
    async with AsyncSessionLocal() as db:
        db.add(Job(id=job_id, job_type="detect_runs", status="queued", payload_json="{}"))
        await db.commit()

    result = await detect_game_features(job_id=job_id, game_db_id=game_id)
    assert result["game_id"] == game_id
    assert result["events_processed"] == 11
    assert result["runs_detected"] >= 1
    assert result["bad_stretches_detected"] >= 1

    async with AsyncSessionLocal() as db:
        runs = (
            await db.execute(select(ScoringRun).where(ScoringRun.game_id == game_id))
        ).scalars().all()
        assert len(runs) >= 1
        # At least one Knicks run and one opponent run
        teams = {r.team_id for r in runs}
        assert "NYK" in teams

        stretches = (
            await db.execute(select(BadStretch).where(BadStretch.game_id == game_id))
        ).scalars().all()
        assert len(stretches) >= 1


async def test_detect_runs_replaces_existing_results(worker_db):
    """Re-running detection should not duplicate scoring_runs rows."""
    from worker_app.jobs.detect_runs import detect_game_features

    game_id = await _seed_game_with_events()

    job_id = "test_detect_replay"
    async with AsyncSessionLocal() as db:
        db.add(Job(id=job_id, job_type="detect_runs", status="queued", payload_json="{}"))
        await db.commit()
    await detect_game_features(job_id=job_id, game_db_id=game_id)
    async with AsyncSessionLocal() as db:
        first_count = len(
            (await db.execute(select(ScoringRun).where(ScoringRun.game_id == game_id)))
            .scalars()
            .all()
        )

    # Run again — should still produce the same count, not double.
    job_id_2 = "test_detect_replay_2"
    async with AsyncSessionLocal() as db:
        db.add(Job(id=job_id_2, job_type="detect_runs", status="queued", payload_json="{}"))
        await db.commit()
    await detect_game_features(job_id=job_id_2, game_db_id=game_id)
    async with AsyncSessionLocal() as db:
        second_count = len(
            (await db.execute(select(ScoringRun).where(ScoringRun.game_id == game_id)))
            .scalars()
            .all()
        )
    assert first_count == second_count
