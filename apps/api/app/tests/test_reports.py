"""Tests for the postgame report generator."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.bad_stretch import BadStretch  # noqa: E402
from app.models.report import Report  # noqa: E402
from app.models.scoring_run import ScoringRun  # noqa: E402


@pytest.fixture(scope="function")
async def report_db() -> AsyncIterator:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from datetime import date

    from app.core.seed_loader import seed_players, seed_teams
    from app.models.game import Game
    from app.models.game_event import GameEvent
    from basketball_core.parsers.play_by_play import parse_events

    async with AsyncSessionLocal() as session:
        await seed_teams(session)
        await seed_players(session)
        # Add a fresh game with events
        game = Game(
            nba_game_id="00224TEST01",
            season="2024-25",
            game_date=date(2024, 11, 1),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110,
            away_score=100,
            status="final",
        )
        session.add(game)
        await session.flush()
        # Simple events for detector
        events_raw = [
            {"event_type": "made_shot", "description": "made 2pt", "period": 1, "clock": "10:00", "team_id": "NYK", "home_score": 2, "away_score": 0},  # noqa: E501
            {"event_type": "made_shot", "description": "made 2pt", "period": 1, "clock": "9:30", "team_id": "NYK", "home_score": 4, "away_score": 0},  # noqa: E501
            {"event_type": "made_shot", "description": "made 3pt", "period": 1, "clock": "9:00", "team_id": "NYK", "home_score": 7, "away_score": 0},  # noqa: E501
            {"event_type": "made_shot", "description": "made 2pt", "period": 1, "clock": "8:30", "team_id": "NYK", "home_score": 9, "away_score": 0},  # noqa: E501
            {"event_type": "made_shot", "description": "made 2pt", "period": 1, "clock": "8:00", "team_id": "BOS", "home_score": 9, "away_score": 2},  # noqa: E501
            {"event_type": "turnover", "description": "Brunson TO", "period": 2, "clock": "6:00", "team_id": "NYK", "home_score": 50, "away_score": 45},  # noqa: E501
            {"event_type": "turnover", "description": "Randle TO", "period": 2, "clock": "5:30", "team_id": "NYK", "home_score": 50, "away_score": 45},  # noqa: E501
            {"event_type": "made_shot", "description": "made 3pt", "period": 2, "clock": "5:00", "team_id": "BOS", "home_score": 50, "away_score": 48},  # noqa: E501
            {"event_type": "made_shot", "description": "made 2pt", "period": 2, "clock": "4:30", "team_id": "BOS", "home_score": 50, "away_score": 50},  # noqa: E501
        ]
        events = parse_events(game.id, events_raw)
        for ev in events:
            session.add(GameEvent(**ev.model_dump(exclude_none=True, exclude={"id"})))
        # Pre-populate one scoring run and one bad stretch
        session.add(
            ScoringRun(
                game_id=game.id,
                team_id="NYK",
                period=1,
                start_sequence=1,
                end_sequence=4,
                start_clock="10:00",
                end_clock="9:00",
                points_for=7,
                points_against=0,
                score_delta=7,
                event_count=4,
                summary="NYK 7-0 run in Q1",
            )
        )
        session.add(
            BadStretch(
                game_id=game.id,
                period=2,
                start_clock="6:00",
                end_clock="4:30",
                score_delta=-3,
                summary='["multiple turnovers", "offensive drought"]',
                likely_causes='["multiple turnovers", "offensive drought"]',
                knicks_turnovers=2,
                knicks_missed_shots=0,
                opponent_fast_breaks=0,
            )
        )
        await session.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_generate_postgame_creates_report_row(report_db):
    from app.services.report_generator import generate_postgame_report

    result = await generate_postgame_report(game_id=1)
    assert result["id"] >= 1
    assert result["title"]
    assert result["turning_point"]
    assert isinstance(result["player_notes"], list)
    assert isinstance(result["suggested_adjustments"], list)
    assert isinstance(result["tool_calls"], list)
    assert len(result["tool_calls"]) >= 4  # game, runs, stretches, snippets, llm

    # Verify persisted
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select as sel
        rows = (await session.execute(sel(Report))).scalars().all()
        assert len(rows) == 1
        assert rows[0].sources_json  # non-empty
        assert rows[0].tool_trace_json


async def test_report_uses_real_runs_for_turning_point(report_db):
    """The mock LLM should use the actual scoring run we seeded."""
    from app.services.report_generator import generate_postgame_report

    result = await generate_postgame_report(game_id=1)
    # We seeded a 7-0 NYK run; that should be in the turning point or best stretch.
    text = (result["turning_point"] + " " + result["best_stretch"]).lower()
    assert "7" in text or "knicks" in text


async def test_report_uses_bad_stretch_for_worst(report_db):
    from app.services.report_generator import generate_postgame_report

    result = await generate_postgame_report(game_id=1)
    assert "Q2" in result["worst_stretch"] or "turnover" in result["worst_stretch"].lower()


async def test_report_for_missing_game_raises(report_db):
    from app.services.report_generator import generate_postgame_report

    with pytest.raises(ValueError, match="not found"):
        await generate_postgame_report(game_id=99999)
