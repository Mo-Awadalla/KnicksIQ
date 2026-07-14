"""Possession-level chunks derived from cached play-by-play rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PossessionChunk:
    chunk_id: str
    game_id: int
    text: str
    metadata: dict[str, Any]
    rows: list[dict[str, Any]]


_POSSESSION_END_TYPES = {"made_shot", "turnover"}


def _event_row(event: Any) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "sequence": event.sequence,
        "period": event.period,
        "clock": event.clock,
        "team_id": event.team_id,
        "player_id": event.player_id,
        "player_name": event.player_name,
        "event_type": event.event_type,
        "description": event.description,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "score_margin": event.score_margin,
    }


def _chunk_text(game: Any, rows: list[dict[str, Any]]) -> str:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    lines = [
        f"{game.game_date} NYK vs {opponent} possession window",
        f"Q{rows[0]['period']} {rows[0]['clock']} to Q{rows[-1]['period']} {rows[-1]['clock']}",
    ]
    lines.extend(
        f"Q{row['period']} {row['clock']} {row['team_id'] or '-'} "
        f"{row['player_name'] or ''}: {row['description']}".strip()
        for row in rows
        if row["description"]
    )
    return "\n".join(lines)


def _metadata(game: Any, possession_index: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    player_ids = sorted({row["player_id"] for row in rows if row["player_id"] is not None})
    player_names = sorted({row["player_name"] for row in rows if row["player_name"]})
    team_ids = sorted({row["team_id"] for row in rows if row["team_id"]})
    return {
        "game_id": game.id,
        "date": str(game.game_date),
        "home_team_id": game.home_team_id,
        "away_team_id": game.away_team_id,
        "season": game.season,
        "season_type": game.season_type,
        "data_status": game.data_status,
        "possession_index": possession_index,
        "start_period": rows[0]["period"],
        "end_period": rows[-1]["period"],
        "start_clock": rows[0]["clock"],
        "end_clock": rows[-1]["clock"],
        "team_ids": team_ids,
        "player_ids": player_ids,
        "player_names": player_names,
        "row_count": len(rows),
        "source_name": game.source_name,
        "source_url": game.source_url,
    }


def build_possession_chunks(game: Any, events: list[Any]) -> list[PossessionChunk]:
    """Build possession-like chunks without changing cached source rows."""
    ordered = sorted(events, key=lambda event: (event.period, event.sequence, event.id or 0))
    chunks: list[PossessionChunk] = []
    current: list[dict[str, Any]] = []
    possession_index = 0
    current_period: int | None = None

    def flush() -> None:
        nonlocal possession_index, current
        if not current:
            return
        metadata = _metadata(game, possession_index, current)
        chunks.append(
            PossessionChunk(
                chunk_id=f"game:{game.id}:poss:{possession_index}",
                game_id=game.id,
                text=_chunk_text(game, current),
                metadata=metadata,
                rows=list(current),
            )
        )
        possession_index += 1
        current = []

    for event in ordered:
        if current_period is not None and event.period != current_period:
            flush()
        current_period = event.period
        current.append(_event_row(event))
        if event.event_type in _POSSESSION_END_TYPES:
            flush()
        elif event.event_type == "rebound" and event.team_id and current:
            descriptions = " ".join(str(row["description"]).lower() for row in current[-2:])
            if "defensive" in descriptions:
                flush()
        elif event.event_type == "period_end":
            flush()

    flush()
    return chunks


def chunk_evidence(chunk: PossessionChunk) -> dict[str, Any]:
    return {
        "type": "possession",
        "game_id": chunk.game_id,
        "possession_id": chunk.chunk_id,
        "date": chunk.metadata["date"],
        "period_window": [chunk.metadata["start_period"], chunk.metadata["end_period"]],
        "clock_window": [chunk.metadata["start_clock"], chunk.metadata["end_clock"]],
        "players": chunk.metadata["player_names"],
        "teams": chunk.metadata["team_ids"],
        "rows": chunk.rows,
    }
