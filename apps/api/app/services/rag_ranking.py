"""Rag ranking."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.models.game import Game
from app.services.possession_chunks import (
    PossessionChunk,
)
from app.services.team_aliases import team_ids_in_text

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RetrievalFilters:
    dates: set[str]
    team_ids: set[str]
    player_terms: set[str]
    periods: set[int]
    last_minutes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "dates": sorted(self.dates),
            "team_ids": sorted(self.team_ids),
            "player_terms": sorted(self.player_terms),
            "periods": sorted(self.periods),
            **({"last_minutes": self.last_minutes} if self.last_minutes is not None else {}),
        }


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def _knicks_result(game: Game) -> str:
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    return "W" if knicks_score > opponent_score else "L"


def build_metadata_filters(query: str) -> RetrievalFilters:
    """Extract strict metadata filters that can be applied before retrieval."""
    q = query.lower()
    dates = set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", q))
    team_ids = team_ids_in_text(query)
    periods = {int(match) for match in re.findall(r"\b(?:q|quarter\s*)([1-4])\b", q)}
    normalized = q.replace("-", " ")
    for period, name in enumerate(("first", "second", "third", "fourth"), 1):
        if re.search(
            rf"\b(?:{name} quarter|{period}(?:st|nd|rd|th) quarter|{period}q)\b", normalized
        ):
            periods.add(period)
    if "after halftime" in normalized or "second half" in normalized:
        periods.update({3, 4})
    if "first half" in normalized:
        periods.update({1, 2})
    minutes_match = re.search(r"\b(?:last|final)\s+(\d+|one|two|three|four|five)\s+minutes?\b", q)
    minute_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    last_minutes = None
    if minutes_match:
        value = minutes_match[1]
        last_minutes = int(value) if value.isdigit() else minute_words[value]
    player_terms = {
        token
        for token in _tokens(query)
        if token
        not in {
            "knicks",
            "game",
            "season",
            "quarter",
            "against",
            "what",
            "happened",
            "with",
            "without",
        }
    }
    return RetrievalFilters(
        dates=dates,
        team_ids=team_ids,
        player_terms=player_terms,
        periods=periods,
        last_minutes=last_minutes,
    )


def _clock_seconds(clock: str) -> int:
    try:
        minutes, seconds = clock.split(":", maxsplit=1)
        return int(minutes) * 60 + int(seconds)
    except (AttributeError, ValueError):
        return 0


def _passes_filters(chunk: PossessionChunk, filters: RetrievalFilters) -> bool:
    metadata = chunk.metadata
    if filters.dates and metadata.get("date") not in filters.dates:
        return False
    if filters.team_ids:
        required_team_ids = filters.team_ids - {"NYK"} or filters.team_ids
        chunk_teams = set(metadata.get("team_ids") or [])
        game_teams = {metadata.get("home_team_id"), metadata.get("away_team_id")}
        if not required_team_ids & (chunk_teams | game_teams):
            return False
    if filters.periods:
        chunk_periods = set(range(int(metadata["start_period"]), int(metadata["end_period"]) + 1))
        if not filters.periods & chunk_periods:
            return False
    return True


def _clip_temporal_chunk(
    chunk: PossessionChunk, filters: RetrievalFilters, final_periods: dict[int, int]
) -> PossessionChunk | None:
    if not filters.periods and filters.last_minutes is None:
        return chunk
    periods = filters.periods
    if not periods and filters.last_minutes is not None:
        periods = {final_periods.get(chunk.game_id, 4)}
    rows = [
        row
        for row in chunk.rows
        if row.get("period") in periods
        and (
            filters.last_minutes is None
            or _clock_seconds(str(row.get("clock", ""))) <= filters.last_minutes * 60
        )
    ]
    if not rows:
        return None
    if rows == chunk.rows:
        return chunk
    before, after = rows[0]["score_before"], rows[-1]["score_after"]
    metadata = {
        **chunk.metadata,
        "start_period": rows[0]["period"],
        "end_period": rows[-1]["period"],
        "start_clock": rows[0]["clock"],
        "end_clock": rows[-1]["clock"],
        "row_count": len(rows),
        "score_before": before,
        "score_after": after,
        "margin_before": before["home"] - before["away"],
        "margin_after": after["home"] - after["away"],
        "player_names": sorted({row["player_name"] for row in rows if row.get("player_name")}),
        "player_ids": sorted({row["player_id"] for row in rows if row.get("player_id")}),
        "unit_type": "event_window",
        "possession_result": None,
    }
    return PossessionChunk(
        chunk_id=chunk.chunk_id,
        game_id=chunk.game_id,
        metadata=metadata,
        rows=rows,
        text=" ".join(
            f"Q{row['period']} {row['clock']} {row.get('description', '')}" for row in rows
        ),
    )


def _bm25ish_score(query_tokens: set[str], text: str) -> float:
    text_tokens = _TOKEN_RE.findall(text.lower())
    if not text_tokens:
        return 0.0
    counts = {token: text_tokens.count(token) for token in query_tokens}
    return sum(count / (1.2 + count) for count in counts.values())


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    k: int = 60,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, (item_id, _score) in enumerate(ranking, start=1):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))
    ordered_ids = sorted(scores, key=lambda item_id: (-scores[item_id], item_id))
    if limit is not None:
        ordered_ids = ordered_ids[:limit]
    return [(item_id, scores[item_id]) for item_id in ordered_ids]


def _rrf_merge(
    rankings: list[list[tuple[PossessionChunk, float]]], limit: int
) -> list[PossessionChunk]:
    chunks: dict[str, PossessionChunk] = {
        chunk.chunk_id: chunk for ranking in rankings for chunk, _score in ranking
    }
    fused = reciprocal_rank_fusion(
        [[(chunk.chunk_id, score) for chunk, score in ranking] for ranking in rankings],
        limit=limit,
    )
    ordered_ids = [chunk_id for chunk_id, _score in fused]
    return [chunks[chunk_id] for chunk_id in ordered_ids[:limit]]


def _lexical_rank_chunks(
    query: str,
    chunks: list[PossessionChunk],
) -> tuple[list[tuple[PossessionChunk, float]], list[tuple[PossessionChunk, float]]]:
    query_tokens = _tokens(query)
    lexical = [
        (chunk, _bm25ish_score(query_tokens, f"{chunk.text} {json.dumps(chunk.metadata)}"))
        for chunk in chunks
    ]
    lexical = [(chunk, score) for chunk, score in lexical if score > 0 or not query_tokens]
    lexical.sort(key=lambda item: (-item[1], item[0].chunk_id))

    player_rank = [
        (
            chunk,
            float(
                len(
                    query_tokens
                    & {
                        token
                        for name in chunk.metadata.get("player_names", [])
                        for token in _tokens(name)
                    }
                )
            ),
        )
        for chunk in chunks
    ]
    player_rank = [(chunk, score) for chunk, score in player_rank if score > 0]
    player_rank.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return lexical, player_rank


def _chunk_from_payload(result_id: str, payload: dict[str, Any]) -> PossessionChunk:
    rows = list(payload.get("raw_rows") or payload.get("rows") or [])
    text = str(payload.get("text") or payload.get("semantic_summary") or "")
    chunk_id = str(payload.get("chunk_id") or result_id)
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"text", "semantic_summary", "raw_rows", "rows", "chunk_id"}
    }
    game_id = int(metadata.get("game_id") or 0)
    return PossessionChunk(
        chunk_id=chunk_id,
        game_id=game_id,
        text=text,
        metadata=metadata,
        rows=rows,
    )
