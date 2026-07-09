"""Job: ingest a list of games (or refresh from the upstream data source).

Pulls games for a given season from the data source and upserts them
into the database. Emits a summary result that the API can surface.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Shared models live in the API package. Worker imports from there.
from app.models.game import Game
from app.models.team import Team
from sqlalchemy import select

from worker_app.adapters import get_data_source, parse_game_date
from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import mark_failed, mark_finished, mark_started

# Path to the API's seed directory. Worker reads from the same JSON
# the API uses at startup.
API_SEED_DIR = (
    Path(__file__).resolve().parents[4] / "apps" / "api" / "app" / "core" / "seed"
)


def _worker_name() -> str:
    return f"worker@{socket.gethostname()}"


def _now_id() -> str:
    return uuid.uuid4().hex


async def ingest_games(
    *,
    job_id: str,
    season: str | None = None,
    include_playoffs: bool = False,
) -> dict[str, Any]:
    """Ingest games from the data source.

    The job_id is created by the API (returned from POST /jobs/ingest/games)
    so the API can stream status back. The worker updates the Job row
    to track progress.
    """
    source = get_data_source(get_settings(), API_SEED_DIR)
    seasons = [season] if season else source.list_seasons()

    inserted: list[int] = []
    skipped: list[str] = []
    async with AsyncSessionLocal() as db:
        await mark_started(db, job_id, _worker_name())
        try:
            for s in seasons:
                for raw in source.list_games(s, include_playoffs=include_playoffs):
                    nba_game_id = raw["nba_game_id"]
                    existing = await db.execute(
                        select(Game).where(Game.nba_game_id == nba_game_id)
                    )
                    if existing.scalar_one_or_none():
                        skipped.append(nba_game_id)
                        continue

                    # Validate both teams exist before inserting.
                    home_id = raw["home_team_id"]
                    away_id = raw["away_team_id"]
                    teams_present = await db.execute(
                        select(Team.id).where(Team.id.in_([home_id, away_id]))
                    )
                    if {row[0] for row in teams_present.all()} != {home_id, away_id}:
                        skipped.append(nba_game_id)
                        continue

                    game = Game(
                        nba_game_id=nba_game_id,
                        season=raw["season"],
                        game_date=parse_game_date(raw["game_date"]),
                        home_team_id=home_id,
                        away_team_id=away_id,
                        home_score=raw["home_score"],
                        away_score=raw["away_score"],
                        status=raw.get("status", "final"),
                        season_type=raw.get("season_type", "regular"),
                        data_status=raw.get("data_status", "summary_only"),
                        source_name=raw.get("source_name", source.__class__.__name__),
                        source_url=raw.get("source_url"),
                        source_game_id=raw.get("source_game_id", nba_game_id),
                        source_fetched_at=datetime.now(UTC),
                        source_payload_hash=raw.get("source_payload_hash"),
                        game_label=raw.get("game_label"),
                        series_name=raw.get("series_name"),
                        series_game_number=raw.get("series_game_number"),
                    )
                    db.add(game)
                    await db.flush()
                    inserted.append(game.id)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            await mark_failed(db, job_id, str(exc))
            raise

        result = {
            "inserted_game_ids": inserted,
            "skipped_nba_game_ids": skipped,
            "seasons_processed": seasons,
            "include_playoffs": include_playoffs,
        }
        await mark_finished(db, job_id, result)
        return result
