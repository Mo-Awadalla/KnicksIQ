"""Seed loader — reads JSON files in this directory and inserts them.

Used both by the lifespan startup (when running in dev) and by tests
to populate an in-memory database.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from basketball_core.parsers.play_by_play import parse_events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.models.team import Team
from app.services.rag import upsert_game_documents

SEED_DIR = Path(__file__).parent / "seed"


def _load(name: str) -> list[dict]:
    with (SEED_DIR / name).open() as f:
        return json.load(f)


def _coerce_game_row(row: dict) -> dict:
    """Convert JSON-loaded string types to the types SQLAlchemy expects."""
    coerced = dict(row)
    if isinstance(coerced.get("game_date"), str):
        coerced["game_date"] = date.fromisoformat(coerced["game_date"])
    return coerced


async def _seed_player_lookup(db: AsyncSession) -> dict[str, int]:
    players = (await db.execute(select(Player.id, Player.full_name))).all()
    lookup: dict[str, int] = {}
    for player_id, full_name in players:
        full_name = str(full_name or "").strip()
        if full_name:
            lookup[full_name.lower()] = int(player_id)
            lookup[full_name.split()[-1].lower()] = int(player_id)
    return lookup


def _attach_seed_player_ids(events: list[dict], player_lookup: dict[str, int]) -> list[dict]:
    out: list[dict] = []
    for event in events:
        row = dict(event)
        if row.get("player_id") is None:
            desc = str(row.get("description") or "").lower()
            for name, nba_player_id in player_lookup.items():
                if name in desc:
                    row["player_id"] = nba_player_id
                    break
        out.append(row)
    return out


def _expand_seed_events_to_full_game(game_row: dict, events: list[dict]) -> list[dict]:
    """Make compact seed fixtures span four periods and end at the final score.

    The checked-in seed data intentionally keeps early Q1 play-by-play short.
    For local dev and tests, we need representative full-game cached events so
    analysis and RAG do not look first-quarter-only.
    """
    if not events or {int(e.get("period", 1)) for e in events} - {1}:
        return events

    last_home = int(events[-1].get("home_score") or 0)
    last_away = int(events[-1].get("away_score") or 0)
    final_home = int(game_row.get("home_score") or last_home)
    final_away = int(game_row.get("away_score") or last_away)
    if (last_home, last_away) == (final_home, final_away):
        return events

    home_team = game_row["home_team_id"]
    away_team = game_row["away_team_id"]
    home_step = max(1, (final_home - last_home) // 6)
    away_step = max(1, (final_away - last_away) // 6)
    home_score = last_home
    away_score = last_away
    expanded = list(events)
    clocks = ("10:24", "7:18", "4:06")
    for period in range(2, 5):
        expanded.append(
            {
                "period": period,
                "clock": "12:00",
                "event_type": "period_start",
                "description": f"Start of {period}Q",
                "home_score": home_score,
                "away_score": away_score,
            }
        )
        for idx, clock in enumerate(clocks):
            if idx % 2 == 0 and home_score < final_home:
                home_score = min(final_home, home_score + home_step)
                expanded.append(
                    {
                        "period": period,
                        "clock": clock,
                        "event_type": "made_shot",
                        "description": f"{home_team} made shot",
                        "team_id": home_team,
                        "home_score": home_score,
                        "away_score": away_score,
                    }
                )
            if away_score < final_away:
                away_score = min(final_away, away_score + away_step)
                expanded.append(
                    {
                        "period": period,
                        "clock": clock,
                        "event_type": "made_shot",
                        "description": f"{away_team} made shot",
                        "team_id": away_team,
                        "home_score": home_score,
                        "away_score": away_score,
                    }
                )
        if period == 4:
            home_score = final_home
            away_score = final_away
        expanded.append(
            {
                "period": period,
                "clock": "0:00",
                "event_type": "period_end",
                "description": f"End of {period}Q",
                "home_score": home_score,
                "away_score": away_score,
            }
        )
    return expanded


async def seed_teams(db: AsyncSession) -> None:
    rows = _load("teams.json")
    for row in rows:
        db.add(Team(**row))
    await db.commit()


async def seed_players(db: AsyncSession) -> None:
    rows = _load("players.json")
    for row in rows:
        db.add(Player(**row))
    await db.commit()


async def seed_games(db: AsyncSession) -> int:
    """Insert games (and their play-by-play events).

    Returns the number of games inserted.
    """
    games = _load("games.json")
    player_lookup = await _seed_player_lookup(db)
    count = 0
    for game_row in games:
        events_raw = _attach_seed_player_ids(
            _expand_seed_events_to_full_game(game_row, game_row.get("events", [])),
            player_lookup,
        )
        game_data = _coerce_game_row({k: v for k, v in game_row.items() if k != "events"})
        game_data.setdefault("season_type", "regular")
        game_data.setdefault("data_status", "events_ready" if events_raw else "summary_only")
        game_data.setdefault("source_name", "seed")
        game_data.setdefault("source_game_id", game_data.get("nba_game_id"))
        game = Game(**game_data)
        db.add(game)
        await db.flush()  # populate game.id for the events
        events = parse_events(game.id, events_raw)
        event_rows: list[GameEvent] = []
        for ev in events:
            event_row = GameEvent(**ev.model_dump(exclude_none=True, exclude={"id"}))
            db.add(event_row)
            event_rows.append(event_row)
        await db.flush()
        await upsert_game_documents(db, game, event_rows)
        count += 1
    await db.commit()
    return count


async def seed_all(db: AsyncSession) -> dict[str, int]:
    """Seed teams, players, and games in dependency order."""
    await seed_teams(db)
    await seed_players(db)
    n_games = await seed_games(db)
    return {
        "teams": len(_load("teams.json")),
        "players": len(_load("players.json")),
        "games": n_games,
    }
