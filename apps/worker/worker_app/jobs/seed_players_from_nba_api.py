"""Job: seed the `players` table from the live NBA.com roster.

Calls `nba_api`'s `commonallplayers` endpoint to fetch the current NBA
player list and upserts each player (keyed on `nba_player_id`).

Only requires that `NBA_DATA_SOURCE=nba_api` — does not need a
specific season. Re-runnable: updates `full_name` and `team_id`
on conflict so trades are reflected in the next run.

# Out of scope (intentionally)

- Position and jersey_number are NOT populated here. The
  `commonallplayers` endpoint doesn't expose them; filling them
  in would require a per-player `commonplayerinfo` call (~600
  calls at our 10/min rate-limit = 1+ hour). Backfill later.
- Historical players (retired, two-way, G-League) are NOT included
  — we filter to active NBA roster members only.
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any

from app.models.game import Game
from app.models.player import Player
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from worker_app.adapters import NbaApiDataSource, get_data_source
from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import mark_failed, mark_finished, mark_started

log = logging.getLogger(__name__)

API_SEED_DIR = Path(__file__).resolve().parents[4] / "apps" / "api" / "app" / "core" / "seed"


def _worker_name() -> str:
    return f"worker@{socket.gethostname()}"


def _load_known_team_trigraphs(seed_dir: Path) -> set[str]:
    with (seed_dir / "teams.json").open() as f:
        return {row["id"] for row in json.load(f)}


async def _upsert_player(
    db: Any,
    nba_player_id: int,
    full_name: str,
    team_trigraph: str | None,
    position: str | None = None,
    jersey_number: str | None = None,
) -> str:
    """Insert or update a single player row keyed on nba_player_id.

    Returns one of: 'inserted', 'updated', 'unchanged'.
    """
    existing = await db.execute(select(Player).where(Player.nba_player_id == nba_player_id))
    row = existing.scalar_one_or_none()
    if row is None:
        db.add(
            Player(
                nba_player_id=nba_player_id,
                full_name=full_name,
                team_id=team_trigraph,
                position=position,
                jersey_number=jersey_number,
            )
        )
        return "inserted"
    changed = False
    if row.full_name != full_name:
        row.full_name = full_name
        changed = True
    if row.team_id != team_trigraph:
        row.team_id = team_trigraph
        changed = True
    if position is not None and row.position != position:
        row.position = position
        changed = True
    if jersey_number is not None and row.jersey_number != jersey_number:
        row.jersey_number = jersey_number
        changed = True
    return "updated" if changed else "unchanged"


async def seed_players_from_nba_api(*, job_id: str) -> dict[str, Any]:
    """Seed the `players` table from `commonallplayers`.

    Active NBA roster members only. Players on teams not in our
    seed `teams.json` are skipped (defensive — we don't know the
    trigraph mapping for non-NBA teams).
    """
    async with AsyncSessionLocal() as db:
        await mark_started(db, job_id, _worker_name())
        try:
            source = get_data_source(get_settings(), API_SEED_DIR)
            if not isinstance(source, NbaApiDataSource):
                raise ValueError(
                    "seed_players_from_nba_api requires NBA_DATA_SOURCE=nba_api; "
                    f"current data_source={get_settings().data_source!r}"
                )

            known_teams = _load_known_team_trigraphs(API_SEED_DIR)

            rows = source.list_active_players()
            log.info("Fetched %d active players from commonallplayers", len(rows))

            counts: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
            for row in rows:
                nba_player_id = row.get("PERSON_ID") or row.get("personId")
                full_name = row.get("DISPLAY_FIRST_LAST") or row.get("displayFirstLast")
                team_abbrev = row.get("TEAM_ABBREVIATION") or row.get("teamAbbreviation")
                roster_status = (
                    row.get("ROSTERSTATUS") or row.get("rosterStatus") or row.get("roster_status")
                )
                if not nba_player_id or not full_name:
                    counts["skipped"] += 1
                    continue
                # 0 / "" teamAbbrev often means free agent or unsigned; skip them.
                team_trigraph = str(team_abbrev).strip().upper() if team_abbrev else None
                if team_trigraph == "" or team_trigraph == "0":
                    team_trigraph = None
                if team_trigraph and team_trigraph not in known_teams:
                    counts["skipped"] += 1
                    continue
                # Roster status 1 = active; 0 = inactive. We keep active only.
                if roster_status is not None and str(roster_status) == "0":
                    counts["skipped"] += 1
                    continue

                try:
                    result = await _upsert_player(
                        db,
                        nba_player_id=int(nba_player_id),
                        full_name=str(full_name),
                        team_trigraph=team_trigraph,
                    )
                    counts[result] += 1
                except IntegrityError as exc:
                    await db.rollback()
                    log.warning("Skipping player %s due to DB error: %s", nba_player_id, exc)
                    counts["skipped"] += 1
                    continue

            await db.commit()
            await mark_finished(db, job_id, counts)
            return counts
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            await mark_failed(db, job_id, str(exc))
            raise


async def seed_season_rosters_from_nba_api(*, job_id: str, season: str) -> dict[str, Any]:
    """Seed historical season rosters for teams in cached games."""
    async with AsyncSessionLocal() as db:
        await mark_started(db, job_id, _worker_name())
        try:
            source = get_data_source(get_settings(), API_SEED_DIR)
            if not isinstance(source, NbaApiDataSource):
                raise ValueError(
                    "seed_season_rosters_from_nba_api requires NBA_DATA_SOURCE=nba_api; "
                    f"current data_source={get_settings().data_source!r}"
                )

            teams = (
                await db.execute(
                    select(Game.home_team_id, Game.away_team_id)
                    .where(Game.season == season)
                    .where((Game.home_team_id.is_not(None)) & (Game.away_team_id.is_not(None)))
                )
            ).all()
            team_ids = sorted({team_id for row in teams for team_id in row if team_id})

            counts: dict[str, int] = {
                "teams": len(team_ids),
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped": 0,
            }
            for team_id in team_ids:
                rows = source.list_team_roster(team_id, season)
                log.info("Fetched %d roster rows for %s %s", len(rows), team_id, season)
                for row in rows:
                    nba_player_id = row.get("PLAYER_ID") or row.get("playerId")
                    full_name = row.get("PLAYER") or row.get("player")
                    if not nba_player_id or not full_name:
                        counts["skipped"] += 1
                        continue
                    position = str(row.get("POSITION") or "").strip() or None
                    jersey_number = str(row.get("NUM") or "").strip() or None
                    try:
                        result = await _upsert_player(
                            db,
                            nba_player_id=int(nba_player_id),
                            full_name=str(full_name),
                            team_trigraph=team_id,
                            position=position,
                            jersey_number=jersey_number,
                        )
                        counts[result] += 1
                    except IntegrityError as exc:
                        await db.rollback()
                        log.warning(
                            "Skipping roster player %s due to DB error: %s",
                            nba_player_id,
                            exc,
                        )
                        counts["skipped"] += 1
                        continue

            await db.commit()
            await mark_finished(db, job_id, counts)
            return counts
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            await mark_failed(db, job_id, str(exc))
            raise
