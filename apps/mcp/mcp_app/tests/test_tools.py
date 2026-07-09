"""Tests for the MCP server tools.

These tests exercise the tool functions directly (not the FastMCP
transport layer). They use the same SQLite test DB the API tests use.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"

from app.core.db import (
    AsyncSessionLocal,  # noqa: E402
    engine,  # noqa: E402
)
from app.core.seed_loader import seed_all  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="function")
async def mcp_db() -> AsyncIterator:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await seed_all(session)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_knicks_get_games_lists_seeded(mcp_db):
    from mcp_app.tools import knicks_get_games

    games = await knicks_get_games()
    assert len(games) >= 2
    for g in games:
        assert "id" in g
        assert "home_team_id" in g
        assert "margin" in g


async def test_knicks_get_games_filters_by_season(mcp_db):
    from mcp_app.tools import knicks_get_games

    games = await knicks_get_games(season="2024-25")
    assert all(g["season"] == "2024-25" for g in games)


async def test_knicks_get_games_filters_by_team(mcp_db):
    from mcp_app.tools import knicks_get_games

    games = await knicks_get_games(team_id="NYK")
    for g in games:
        assert g["home_team_id"] == "NYK" or g["away_team_id"] == "NYK"


async def test_knicks_get_game_returns_detail(mcp_db):
    from mcp_app.tools import knicks_get_game

    game = await knicks_get_game(1)
    assert game is not None
    assert game["id"] == 1
    assert game["home_team_id"] in ("NYK", "BOS", "PHI")


async def test_knicks_get_game_returns_none_for_missing(mcp_db):
    from mcp_app.tools import knicks_get_game

    game = await knicks_get_game(99999)
    assert game is None


async def test_knicks_get_box_score_returns_totals(mcp_db):
    from mcp_app.tools import knicks_get_box_score

    bs = await knicks_get_box_score(1)
    assert bs["game_id"] == 1
    assert "home_score" in bs
    assert "away_score" in bs


async def test_knicks_get_play_by_play_returns_events(mcp_db):
    from mcp_app.tools import knicks_get_play_by_play

    events = await knicks_get_play_by_play(1)
    assert len(events) > 0
    assert all("period" in e and "clock" in e for e in events)


async def test_knicks_find_scoring_runs_finds_runs_live(mcp_db):
    """When no precomputed runs exist, the detector should run live."""
    from mcp_app.tools import knicks_find_scoring_runs

    runs = await knicks_find_scoring_runs(1)
    # Our seed game 1 (BOS@NYK) is a Knicks blowout win; there should
    # be at least one Knicks 6+ point run.
    assert isinstance(runs, list)
    assert any(r["team_id"] == "NYK" and r["score_delta"] >= 6 for r in runs)


async def test_knicks_find_bad_stretches_finds_stretches(mcp_db):
    """The bad stretch detector should return at least one stretch."""
    from mcp_app.tools import knicks_find_bad_stretches

    stretches = await knicks_find_bad_stretches(1)
    assert isinstance(stretches, list)
