"""MCP tool implementations.

Each tool reads from the database and returns JSON-serializable
results. All tools are read-only by default — the MCP server
never mutates game data.

Tools are exported as a dict for FastMCP registration. The function
names match the required `knicks.*` namespace.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.bad_stretch import BadStretch
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.scoring_run import ScoringRun
from basketball_core.detectors.bad_stretch import detect_bad_stretches
from basketball_core.detectors.scoring_run import detect_scoring_runs
from basketball_core.parsers.play_by_play import parse_events
from sqlalchemy import select

from mcp_app.logging_middleware import tool_call
from mcp_app.schemas import (
    BadStretchModel,
    GameEventModel,
    GameSummary,
    ScoringRunModel,
)


def _to_summary(game: Game) -> dict[str, Any]:
    return GameSummary(
        id=game.id,
        nba_game_id=game.nba_game_id,
        season=game.season,
        game_date=game.game_date,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        home_score=game.home_score,
        away_score=game.away_score,
        status=game.status,
        margin=game.home_score - game.away_score,
    ).model_dump(mode="json")


async def knicks_get_games(
    season: str | None = None,
    team_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List Knicks games. Optional season and team filters.

    Returns a list of game summaries. Use `knicks.get_game` to fetch
    the full play-by-play for a single game.
    """
    with tool_call("knicks.get_games", season=season, team_id=team_id, limit=limit):
        async with AsyncSessionLocal() as db:
            stmt = select(Game)
            if season:
                stmt = stmt.where(Game.season == season)
            if team_id:
                stmt = stmt.where(
                    (Game.home_team_id == team_id) | (Game.away_team_id == team_id)
                )
            stmt = stmt.order_by(Game.game_date.desc()).limit(limit)
            games = (await db.execute(stmt)).scalars().all()
            return [_to_summary(g) for g in games]


async def knicks_get_game(game_id: int) -> dict[str, Any] | None:
    """Get a single game's full detail.

    Returns None if the game is not found.
    """
    with tool_call("knicks.get_game", game_id=game_id):
        async with AsyncSessionLocal() as db:
            game = await db.get(Game, game_id)
            if not game:
                return None
            return _to_summary(game)


async def knicks_get_box_score(game_id: int) -> dict[str, Any]:
    """Return a high-level 'box score' style summary.

    The seed data we ship doesn't have per-player box score rows;
    this returns the team-level totals (final score, status, period
    summaries if available). Replace this with a richer box score
    table once a live data source is wired in.
    """
    with tool_call("knicks.get_box_score", game_id=game_id):
        async with AsyncSessionLocal() as db:
            game = await db.get(Game, game_id)
            if not game:
                return {"error": "game_not_found", "game_id": game_id}
            return {
                "game_id": game.id,
                "home_team_id": game.home_team_id,
                "away_team_id": game.away_team_id,
                "home_score": game.home_score,
                "away_score": game.away_score,
                "status": game.status,
                "margin": game.home_score - game.away_score,
            }


async def knicks_get_play_by_play(
    game_id: int, period: int | None = None
) -> list[dict[str, Any]]:
    """Get the normalized play-by-play events for a game."""
    with tool_call("knicks.get_play_by_play", game_id=game_id, period=period):
        async with AsyncSessionLocal() as db:
            stmt = (
                select(GameEvent)
                .where(GameEvent.game_id == game_id)
                .order_by(GameEvent.period, GameEvent.sequence)
            )
            if period is not None:
                stmt = stmt.where(GameEvent.period == period)
            events = (await db.execute(stmt)).scalars().all()
            return [
                GameEventModel(
                    sequence=e.sequence,
                    period=e.period,
                    clock=e.clock,
                    team_id=e.team_id,
                    player_id=e.player_id,
                    event_type=e.event_type,
                    description=e.description,
                    home_score=e.home_score,
                    away_score=e.away_score,
                    score_margin=e.score_margin,
                ).model_dump()
                for e in events
            ]


async def _events_as_domain(game_id: int):
    """Load events as basketball-core domain models (used by detectors)."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(GameEvent)
            .where(GameEvent.game_id == game_id)
            .order_by(GameEvent.period, GameEvent.sequence)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            parse_events(
                game_id,
                [
                    {
                        "event_type": e.event_type,
                        "description": e.description,
                        "period": e.period,
                        "clock": e.clock,
                        "team_id": e.team_id,
                        "home_score": e.home_score,
                        "away_score": e.away_score,
                    }
                ],
            )[0]
            for e in rows
        ]


async def knicks_find_scoring_runs(
    game_id: int, team_id: str | None = None
) -> list[dict[str, Any]]:
    """Find scoring runs in a game.

    If a precomputed `scoring_runs` row exists for the game, it is
    returned. Otherwise, the detector is run in real time on the
    play-by-play.
    """
    with tool_call("knicks.find_scoring_runs", game_id=game_id, team_id=team_id):
        async with AsyncSessionLocal() as db:
            stmt = (
                select(ScoringRun)
                .where(ScoringRun.game_id == game_id)
                .order_by(ScoringRun.period, ScoringRun.start_sequence)
            )
            if team_id:
                stmt = stmt.where(ScoringRun.team_id == team_id)
            cached = (await db.execute(stmt)).scalars().all()
            if cached:
                return [
                    ScoringRunModel(
                        team_id=r.team_id,
                        period=r.period,
                        start_clock=r.start_clock,
                        end_clock=r.end_clock,
                        points_for=r.points_for,
                        points_against=r.points_against,
                        score_delta=r.score_delta,
                        event_count=r.event_count,
                        summary=r.summary,
                    ).model_dump()
                    for r in cached
                ]

        # Fallback: run detector live.
        events = await _events_as_domain(game_id)
        runs = detect_scoring_runs(events)
        if team_id:
            runs = [r for r in runs if r.team_id == team_id]
        return [
            ScoringRunModel(
                team_id=r.team_id,
                period=r.period,
                start_clock=r.start_clock,
                end_clock=r.end_clock,
                points_for=r.points_for,
                points_against=r.points_against,
                score_delta=r.score_delta,
                event_count=r.event_count,
                summary=r.summary,
            ).model_dump()
            for r in runs
        ]


async def knicks_find_bad_stretches(game_id: int) -> list[dict[str, Any]]:
    """Find bad stretches (opponent runs + droughts + turnover clusters)."""
    with tool_call("knicks.find_bad_stretches", game_id=game_id):
        async with AsyncSessionLocal() as db:
            stmt = (
                select(BadStretch)
                .where(BadStretch.game_id == game_id)
                .order_by(BadStretch.period, BadStretch.start_clock)
            )
            cached = (await db.execute(stmt)).scalars().all()
            if cached:
                return [
                    BadStretchModel(
                        period=s.period,
                        start_clock=s.start_clock,
                        end_clock=s.end_clock,
                        score_delta=s.score_delta,
                        summary=s.summary,
                        likely_causes=json.loads(s.likely_causes) if s.likely_causes else [],
                        knicks_turnovers=s.knicks_turnovers,
                        knicks_missed_shots=s.knicks_missed_shots,
                    ).model_dump()
                    for s in cached
                ]

        events = await _events_as_domain(game_id)
        stretches = detect_bad_stretches(events)
        return [
            BadStretchModel(
                period=s.period,
                start_clock=s.start_clock,
                end_clock=s.end_clock,
                score_delta=s.score_delta,
                summary=s.summary,
                likely_causes=s.likely_causes,
                knicks_turnovers=s.knicks_turnovers,
                knicks_missed_shots=s.knicks_missed_shots,
            ).model_dump()
            for s in stretches
        ]


# Tool registry — name → callable. FastMCP iterates this at startup.
TOOLS = {
    "knicks.get_games": knicks_get_games,
    "knicks.get_game": knicks_get_game,
    "knicks.get_box_score": knicks_get_box_score,
    "knicks.get_play_by_play": knicks_get_play_by_play,
    "knicks.find_scoring_runs": knicks_find_scoring_runs,
    "knicks.find_bad_stretches": knicks_find_bad_stretches,
}
