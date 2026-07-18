"""Sequence-aware possession and event-window chunks from cached play-by-play."""

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
_ADMINISTRATIVE_TYPES = {"substitution", "timeout"}


def _event_row(
    event: Any,
    *,
    score_before: tuple[int, int],
) -> dict[str, Any]:
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
        "score_before": {"home": score_before[0], "away": score_before[1]},
        "score_after": {"home": event.home_score, "away": event.away_score},
    }


def _chunk_text(
    game: Any,
    rows: list[dict[str, Any]],
    *,
    unit_type: str,
    possession_result: str | None,
) -> str:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    before = rows[0]["score_before"]
    after = rows[-1]["score_after"]
    lines = [
        f"{game.game_date} vs {opponent}, Q{rows[0]['period']} "
        f"{rows[0]['clock']}-{rows[-1]['clock']}.",
        f"The {unit_type.replace('_', ' ')} began at "
        f"{game.away_team_id} {before['away']}-{before['home']} {game.home_team_id} "
        f"and ended at {game.away_team_id} {after['away']}-{after['home']} "
        f"{game.home_team_id}.",
    ]
    lines.extend(
        f"Q{row['period']} {row['clock']} {row['team_id'] or '-'} "
        f"{row['player_name'] or ''}: {row['description']}".strip()
        for row in rows
        if row["description"]
    )
    if possession_result:
        lines.append(f"Sequence result: {possession_result}.")
    return "\n".join(lines)


def _metadata(
    game: Any,
    possession_index: int,
    rows: list[dict[str, Any]],
    *,
    unit_type: str,
    possession_result: str | None,
) -> dict[str, Any]:
    player_ids = sorted({row["player_id"] for row in rows if row["player_id"] is not None})
    player_names = sorted({row["player_name"] for row in rows if row["player_name"]})
    team_ids = sorted({row["team_id"] for row in rows if row["team_id"]})
    offense_team_id = next(
        (
            row["team_id"]
            for row in rows
            if row["team_id"]
            and row["event_type"] not in {"period_start", "period_end", "substitution", "timeout"}
        ),
        None,
    )
    defense_team_id = next(
        (
            team_id
            for team_id in (game.home_team_id, game.away_team_id)
            if team_id != offense_team_id
        ),
        None,
    )
    return {
        "game_id": game.id,
        "date": str(game.game_date),
        "home_team_id": game.home_team_id,
        "away_team_id": game.away_team_id,
        "season": game.season,
        "season_type": game.season_type,
        "data_status": game.data_status,
        "possession_index": possession_index,
        "sequence_id": f"game:{game.id}:poss:{possession_index}",
        "previous_sequence_id": None,
        "next_sequence_id": None,
        "unit_type": unit_type,
        "start_period": rows[0]["period"],
        "end_period": rows[-1]["period"],
        "start_clock": rows[0]["clock"],
        "end_clock": rows[-1]["clock"],
        "team_ids": team_ids,
        "player_ids": player_ids,
        "player_names": player_names,
        "row_count": len(rows),
        "score_before": rows[0]["score_before"],
        "score_after": rows[-1]["score_after"],
        "margin_before": rows[0]["score_before"]["home"] - rows[0]["score_before"]["away"],
        "margin_after": rows[-1]["score_after"]["home"] - rows[-1]["score_after"]["away"],
        "offense_team_id": offense_team_id,
        "defense_team_id": defense_team_id,
        "normalized_event_types": sorted({row["event_type"] for row in rows}),
        "possession_result": possession_result,
        "lineup_ids": [],
        "source_name": game.source_name,
        "source_url": game.source_url,
    }


def build_possession_chunks(
    game: Any,
    events: list[Any],
    *,
    contextual_event_windows: bool = True,
) -> list[PossessionChunk]:
    """Build confident possessions, otherwise honestly labeled event windows."""
    ordered = sorted(events, key=lambda event: (event.period, event.sequence, event.id or 0))
    chunks: list[PossessionChunk] = []
    current: list[dict[str, Any]] = []
    possession_index = 0
    current_period: int | None = None
    pending_end = False
    confident_possession = True
    possession_result: str | None = None
    score = (0, 0)

    def flush() -> None:
        nonlocal possession_index
        nonlocal current
        nonlocal pending_end
        nonlocal confident_possession
        nonlocal possession_result
        if not current:
            return
        unit_type = "possession" if confident_possession and possession_result else "event_window"
        metadata = _metadata(
            game,
            possession_index,
            current,
            unit_type=unit_type,
            possession_result=possession_result if unit_type == "possession" else None,
        )
        chunks.append(
            PossessionChunk(
                chunk_id=f"game:{game.id}:poss:{possession_index}",
                game_id=game.id,
                text=_chunk_text(
                    game,
                    current,
                    unit_type=unit_type,
                    possession_result=metadata["possession_result"],
                ),
                metadata=metadata,
                rows=list(current),
            )
        )
        possession_index += 1
        current = []
        pending_end = False
        confident_possession = True
        possession_result = None

    for event in ordered:
        if current_period is not None and event.period != current_period:
            flush()
        current_period = event.period
        description = str(event.description or "").lower()
        continuation = event.event_type in {"free_throw", "foul", *_ADMINISTRATIVE_TYPES} or any(
            term in description for term in ("review", "overturn", "technical", "flagrant")
        )
        if pending_end and not continuation:
            flush()
        current.append(_event_row(event, score_before=score))
        score = (event.home_score, event.away_score)

        if any(term in description for term in ("review", "overturn", "clear path")):
            confident_possession = False
        if event.event_type == "made_shot":
            pending_end = True
            possession_result = "made_shot"
        elif event.event_type == "turnover":
            pending_end = True
            possession_result = "turnover"
        elif event.event_type == "free_throw":
            # Consecutive attempts and and-one continuations remain together.
            pending_end = True
            possession_result = "free_throws"
        elif event.event_type == "rebound" and event.team_id:
            if "offensive" in description:
                pending_end = False
                possession_result = None
            elif "defensive" in description:
                pending_end = True
                possession_result = "defensive_rebound"
            else:
                confident_possession = False
        elif event.event_type == "jump_ball":
            confident_possession = False
            pending_end = "gains possession" in description
        elif event.event_type == "period_end":
            flush()
        if not contextual_event_windows and pending_end:
            flush()

    flush()
    linked: list[PossessionChunk] = []
    for index, chunk in enumerate(chunks):
        metadata = {
            **chunk.metadata,
            "previous_sequence_id": chunks[index - 1].chunk_id if index else None,
            "next_sequence_id": chunks[index + 1].chunk_id if index + 1 < len(chunks) else None,
        }
        linked.append(
            PossessionChunk(
                chunk_id=chunk.chunk_id,
                game_id=chunk.game_id,
                text=chunk.text,
                metadata=metadata,
                rows=chunk.rows,
            )
        )
    return linked


def expand_neighboring_sequences(
    selected: list[PossessionChunk],
    all_chunks: list[PossessionChunk],
    *,
    radius: int = 1,
) -> list[PossessionChunk]:
    """Expand after ranking and collapse overlapping windows into citation units."""
    by_game: dict[int, list[PossessionChunk]] = {}
    for chunk in all_chunks:
        by_game.setdefault(chunk.game_id, []).append(chunk)
    for chunks in by_game.values():
        chunks.sort(key=lambda item: int(item.metadata.get("possession_index", 0)))

    intervals: dict[int, list[tuple[int, int]]] = {}
    for chunk in selected:
        game_chunks = by_game.get(chunk.game_id, [])
        positions = {item.chunk_id: index for index, item in enumerate(game_chunks)}
        index = positions.get(chunk.chunk_id)
        if index is None:
            continue
        intervals.setdefault(chunk.game_id, []).append(
            (max(0, index - radius), min(len(game_chunks) - 1, index + radius))
        )

    expanded: list[PossessionChunk] = []
    for game_id, spans in intervals.items():
        merged_spans: list[list[int]] = []
        for start, end in sorted(spans):
            if merged_spans and start <= merged_spans[-1][1] + 1:
                merged_spans[-1][1] = max(merged_spans[-1][1], end)
            else:
                merged_spans.append([start, end])
        game_chunks = by_game[game_id]
        for start, end in merged_spans:
            members = game_chunks[start : end + 1]
            rows = [row for member in members for row in member.rows]
            first, last = members[0], members[-1]
            metadata = {
                **first.metadata,
                "end_period": last.metadata["end_period"],
                "end_clock": last.metadata["end_clock"],
                "score_after": last.metadata["score_after"],
                "margin_after": last.metadata["margin_after"],
                "row_count": len(rows),
                "unit_type": "event_window",
                "possession_result": None,
                "citation_sequence_ids": [member.chunk_id for member in members],
                "next_sequence_id": last.metadata.get("next_sequence_id"),
            }
            expanded.append(
                PossessionChunk(
                    chunk_id=f"window:{first.chunk_id}:{last.chunk_id}",
                    game_id=game_id,
                    text="\n".join(member.text for member in members),
                    metadata=metadata,
                    rows=rows,
                )
            )
    return expanded


def chunk_evidence(chunk: PossessionChunk) -> dict[str, Any]:
    return {
        "type": chunk.metadata.get("unit_type", "event_window"),
        "game_id": chunk.game_id,
        "possession_id": chunk.chunk_id,
        "date": chunk.metadata["date"],
        "period_window": [chunk.metadata["start_period"], chunk.metadata["end_period"]],
        "clock_window": [chunk.metadata["start_clock"], chunk.metadata["end_clock"]],
        "players": chunk.metadata["player_names"],
        "teams": chunk.metadata["team_ids"],
        "score_before": chunk.metadata.get("score_before"),
        "score_after": chunk.metadata.get("score_after"),
        "margin_before": chunk.metadata.get("margin_before"),
        "margin_after": chunk.metadata.get("margin_after"),
        "offense_team_id": chunk.metadata.get("offense_team_id"),
        "defense_team_id": chunk.metadata.get("defense_team_id"),
        "possession_result": chunk.metadata.get("possession_result"),
        "sequence_ids": chunk.metadata.get("citation_sequence_ids", [chunk.chunk_id]),
        "rows": chunk.rows,
    }
