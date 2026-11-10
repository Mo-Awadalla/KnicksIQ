"""Load and verify canonical SQL rows for local restore mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import Game, GameEvent
from app.services.analyst_provenance import canonical_digest as digest
from app.services.analyst_provenance import event_projection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class SqlRow:
    canonical_id: str
    collection: str
    projection: dict[str, Any]
    row_id: int
    release_id: int
    game_id: int
    player_id: int | None


async def load_event_rows(
    session: AsyncSession,
    release_id: int,
    game_by_id: dict[int, Game],
    actual: dict[str, dict[str, list[SqlRow]]],
    problems: list[str],
) -> None:
    events = (
        await session.execute(
            select(GameEvent)
            .join(Game, GameEvent.game_id == Game.id)
            .where(Game.release_id == release_id)
            .options(selectinload(GameEvent.player))
        )
    ).scalars()
    for event in events:
        game = game_by_id.get(event.game_id)
        if game is None:
            problems.append(f"game_events:{event.id}: game {event.game_id} is not in this release")
            continue
        canonical = f"event:{game.nba_game_id}:{event.sequence}"
        projection = event_projection(game, event)
        actual["game_events"].setdefault(canonical, []).append(
            SqlRow(
                canonical, "game_events", projection, event.id, release_id, game.id, event.player_id
            )
        )


def verify_rows(
    expected: dict[str, dict[str, dict[str, Any]]],
    actual: dict[str, dict[str, list[SqlRow]]],
    problems: list[str],
) -> tuple[dict[str, SqlRow], dict[str, int]]:
    verified_rows: dict[str, SqlRow] = {}
    counts: dict[str, int] = {}
    for collection, expected_rows in expected.items():
        counts[collection] = len(expected_rows)
        for canonical, raw in expected_rows.items():
            found = actual[collection].get(canonical, [])
            if not found:
                problems.append(f"{canonical}: missing SQL row")
                continue
            if len(found) > 1:
                problems.append(f"{canonical}: duplicate SQL rows")
                continue
            row = found[0]
            differing = [
                field for field, value in raw.items() if row.projection.get(field) != value
            ]
            if differing:
                problems.extend(
                    f"{canonical}: field {field} differs "
                    f"(sql={row.projection.get(field)!r}, bundle={raw[field]!r})"
                    for field in differing
                )
                continue
            if digest(row.projection) != digest(raw):
                problems.append(f"{canonical}: canonical row digest differs")
                continue
            verified_rows[canonical] = row
        for canonical in actual[collection]:
            if canonical not in expected_rows:
                problems.append(f"{canonical}: extra SQL row")
    return verified_rows, counts
