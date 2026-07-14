"""Job: ingest play-by-play events for a single game.

Reads the source's event list and upserts into `game_events`. The
events are normalized by `basketball_core.parsers.play_by_play`
before being inserted.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.rag import upsert_game_documents
from basketball_core.parsers.play_by_play import parse_events
from sqlalchemy import delete, select

from worker_app.adapters import get_data_source
from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import mark_failed, mark_finished, mark_started

API_SEED_DIR = Path(__file__).resolve().parents[4] / "apps" / "api" / "app" / "core" / "seed"


def _worker_name() -> str:
    return f"worker@{socket.gethostname()}"


async def _build_player_id_map(db: Any, raw_events: list[dict[str, Any]]) -> dict[int, int]:
    """Map nba_player_id (int) -> internal players.id (int) for the given events.

    Players missing from the DB are inserted with the name/team carried
    by the source event so play-by-play rows can still resolve names.
    This is the only DB-side translation the live data source requires;
    team_ids are already trigraphs in the event dict.
    """
    nba_ids = {ev["player_id"] for ev in raw_events if ev.get("player_id") is not None}
    if not nba_ids:
        return {}
    rows = await db.execute(
        select(Player.id, Player.nba_player_id).where(Player.nba_player_id.in_(nba_ids))
    )
    player_id_map = {nba_id: internal_id for internal_id, nba_id in rows.all()}
    missing_ids = nba_ids - set(player_id_map)
    if missing_ids:
        for nba_player_id in missing_ids:
            source_event = next(ev for ev in raw_events if ev.get("player_id") == nba_player_id)
            full_name = str(source_event.get("player_name") or "").strip()
            if not full_name:
                full_name = f"NBA Player {nba_player_id}"
            db.add(
                Player(
                    nba_player_id=nba_player_id,
                    full_name=full_name,
                    team_id=source_event.get("team_id"),
                )
            )
        await db.flush()
        rows = await db.execute(
            select(Player.id, Player.nba_player_id).where(Player.nba_player_id.in_(nba_ids))
        )
        player_id_map = {nba_id: internal_id for internal_id, nba_id in rows.all()}
    return player_id_map


async def ingest_game_detail(
    *,
    job_id: str,
    game_db_id: int,
) -> dict[str, Any]:
    """Ingest the play-by-play events for a single game (by internal id)."""
    async with AsyncSessionLocal() as db:
        await mark_started(db, job_id, _worker_name())
        try:
            game = await db.get(Game, game_db_id)
            if not game:
                raise ValueError(f"Game {game_db_id} not found")

            source = get_data_source(get_settings(), API_SEED_DIR)
            raw = source.get_game(game.nba_game_id)
            if not raw:
                raise ValueError(f"No source data for {game.nba_game_id}")

            raw_events: list[dict[str, Any]] = raw.get("events", [])
            player_id_map = await _build_player_id_map(db, raw_events)

            # Wipe and re-insert events. Cheap and avoids dedup logic.
            await db.execute(delete(GameEvent).where(GameEvent.game_id == game.id))

            events = parse_events(game.id, raw_events)
            event_rows: list[GameEvent] = []
            unresolved_players = 0
            for ev in events:
                payload = ev.model_dump(exclude_none=True, exclude={"id"})
                nba_pid = payload.get("player_id")
                if nba_pid is not None and nba_pid in player_id_map:
                    payload["player_id"] = player_id_map[nba_pid]
                elif nba_pid is not None and nba_pid not in player_id_map:
                    payload["player_id"] = None
                    unresolved_players += 1
                event_row = GameEvent(**payload)
                db.add(event_row)
                event_rows.append(event_row)

            game.data_status = "events_ready" if events else "summary_only"
            game.source_name = raw.get("source_name", source.__class__.__name__)
            game.source_url = raw.get("source_url")
            game.source_game_id = raw.get("source_game_id", game.nba_game_id)
            game.source_fetched_at = datetime.now(UTC)
            game.source_payload_hash = raw.get("source_payload_hash")
            await db.flush()
            await upsert_game_documents(db, game, event_rows)

            await db.commit()

            result = {
                "game_id": game.id,
                "nba_game_id": game.nba_game_id,
                "events_ingested": len(events),
                "unresolved_players": unresolved_players,
            }
            await mark_finished(db, job_id, result)
            return result
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            await mark_failed(db, job_id, str(exc))
            raise
