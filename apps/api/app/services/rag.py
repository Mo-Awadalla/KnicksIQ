"""Small retrieval layer for season documents."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.models.chunk_model import DocumentChunk
from app.models.dataset_release import DatasetRelease
from app.models.document import Document
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.embeddings import embed_texts
from app.services.possession_chunks import PossessionChunk, build_possession_chunks
from app.services.qdrant_client import is_qdrant_healthy, search_possessions
from app.services.releases import restrict_to_active_release
from app.services.reranker import rerank_candidates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

_TOKEN_RE = re.compile(r"[a-z0-9]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    document_id: int
    title: str
    text: str
    score: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievalFilters:
    dates: set[str]
    team_ids: set[str]
    player_terms: set[str]
    periods: set[int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dates": sorted(self.dates),
            "team_ids": sorted(self.team_ids),
            "player_terms": sorted(self.player_terms),
            "periods": sorted(self.periods),
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
    team_ids = {
        token.upper()
        for token in re.findall(r"\b[A-Z]{2,3}\b", query)
        if token.upper() in {"NYK", "TOR", "BOS", "MIA", "MIL", "PHI", "CHI", "BKN"}
    }
    if "knicks" in q:
        team_ids.add("NYK")
    periods = {int(match) for match in re.findall(r"\b(?:q|quarter\s*)([1-4])\b", q)}
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
        chunk_teams = set(metadata.get("team_ids") or [])
        game_teams = {metadata.get("home_team_id"), metadata.get("away_team_id")}
        if not filters.team_ids & (chunk_teams | game_teams):
            return False
    if filters.periods:
        chunk_periods = set(range(int(metadata["start_period"]), int(metadata["end_period"]) + 1))
        if not filters.periods & chunk_periods:
            return False
    return True


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


def build_game_document_body(game: Game, events: list[GameEvent]) -> str:
    result = "won" if game.home_score > game.away_score else "lost"
    if game.away_team_id == "NYK":
        knicks_score = game.away_score
        opponent = game.home_team_id
        opponent_score = game.home_score
    else:
        knicks_score = game.home_score
        opponent = game.away_team_id
        opponent_score = game.away_score
    lines = [
        f"Knicks {result} {knicks_score}-{opponent_score} against {opponent} on {game.game_date}.",
        f"Season {game.season}; season type {game.season_type}; data status {game.data_status}.",
    ]
    if events:
        lines.append("Play-by-play highlights:")
        lines.extend(
            f"Q{event.period} {event.clock} {event.team_id or '-'}: {event.description}"
            for event in events[:40]
            if event.description
        )
    return "\n".join(lines)


async def upsert_game_documents(
    db: AsyncSession,
    game: Game,
    events: list[GameEvent],
    embedding_json: str | None = None,
) -> int:
    """Replace generated RAG docs/chunks for one game."""
    existing = (
        (
            await db.execute(
                select(Document).where(
                    Document.game_id == game.id,
                    Document.source_type.in_(("game_summary", "play_by_play")),
                )
            )
        )
        .scalars()
        .all()
    )
    for doc in existing:
        await db.delete(doc)
    await db.flush()

    body = build_game_document_body(game, events)
    doc_type = "play_by_play" if events else "game_summary"
    doc = Document(
        source_type=doc_type,
        title=f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
        body=body,
        game_id=game.id,
        team_id="NYK",
    )
    db.add(doc)
    await db.flush()

    metadata = {
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": game.home_team_id if game.away_team_id == "NYK" else game.away_team_id,
        "result": _knicks_result(game),
        "season_type": game.season_type,
        "doc_type": doc_type,
        "data_status": game.data_status,
        "source_name": game.source_name,
        "source_url": game.source_url,
    }
    db.add(
        DocumentChunk(
            document_id=doc.id,
            sequence=0,
            text=body,
            embedding_json=embedding_json,
            metadata_json=json.dumps(metadata),
        )
    )
    return 1


async def search_season_docs(
    db: AsyncSession,
    query: str,
    *,
    season: str | None = "2025-26",
    limit: int = 5,
) -> list[SearchResult]:
    q_tokens = _tokens(query)
    stmt = select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id)
    if season:
        stmt = stmt.join(Game, Game.id == Document.game_id).where(Game.season == season)
    rows = (await db.execute(stmt)).all()
    results: list[SearchResult] = []
    for chunk, doc in rows:
        haystack = f"{doc.title} {chunk.text}"
        score = len(q_tokens & _tokens(haystack))
        if score == 0 and q_tokens:
            continue
        metadata = chunk.chunk_metadata
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                document_id=doc.id,
                title=doc.title,
                text=chunk.text,
                score=score,
                metadata=metadata,
            )
        )
    results.sort(key=lambda r: (-r.score, r.chunk_id))
    return results[:limit]


async def search_possession_chunks(
    db: AsyncSession,
    query: str,
    *,
    season: str = "2025-26",
    limit: int = 5,
    trace: list[dict[str, Any]] | None = None,
) -> tuple[list[PossessionChunk], RetrievalFilters]:
    """Search possession chunks derived from cached play-by-play rows.

    Dense vector/Qdrant and cross-encoder providers can replace the local
    scoring later. The shape here already enforces the required route: metadata
    filters first, then lexical/semantic rankings merged with RRF.
    """
    filters = build_metadata_filters(query)
    game_stmt = (
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date.desc())
    )
    game_stmt = restrict_to_active_release(game_stmt)
    if filters.dates:
        parsed_dates = [date.fromisoformat(value) for value in filters.dates]
        game_stmt = game_stmt.where(Game.game_date.in_(parsed_dates))
    games = list((await db.execute(game_stmt)).scalars().all())
    game_ids = [game.id for game in games]
    if not game_ids:
        return [], filters

    event_rows = (
        (
            await db.execute(
                select(GameEvent)
                .options(selectinload(GameEvent.player))
                .where(GameEvent.game_id.in_(game_ids))
                .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    events_by_game: dict[int, list[GameEvent]] = {}
    for event in event_rows:
        events_by_game.setdefault(event.game_id, []).append(event)

    chunks: list[PossessionChunk] = []
    for game in games:
        chunks.extend(build_possession_chunks(game, events_by_game.get(game.id, [])))
    chunks = [chunk for chunk in chunks if _passes_filters(chunk, filters)]

    t0 = time.perf_counter()
    lexical, player_rank = _lexical_rank_chunks(query, chunks)
    if trace is not None:
        trace.append(
            {
                "tool": "lexical_search",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": len(lexical),
            }
        )

    settings = get_settings()
    qdrant_filters = filters.as_dict()
    if getattr(settings, "is_production", False):
        active_version = (
            await db.execute(
                select(DatasetRelease.version).where(
                    DatasetRelease.status == "active",
                    DatasetRelease.validation_passed.is_(True),
                )
            )
        ).scalar_one_or_none()
        if active_version:
            qdrant_filters["data_version"] = active_version
    dense_rank: list[tuple[PossessionChunk, float]] = []
    if settings.rag_hybrid_enabled and settings.rag_qdrant_enabled:
        try:
            if is_qdrant_healthy():
                t0 = time.perf_counter()
                query_embedding: list[float] | str = (
                    query
                    if getattr(settings, "rag_qdrant_cloud_inference", False)
                    else embed_texts([query])[0]
                )
                if trace is not None:
                    trace.append(
                        {
                            "tool": (
                                "qdrant_cloud_inference"
                                if isinstance(query_embedding, str)
                                else "embed_query"
                            ),
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                            "result_count": 1,
                        }
                    )
                t0 = time.perf_counter()
                dense_results = search_possessions(
                    query_embedding,
                    qdrant_filters,
                    max(limit * 10, settings.rag_rerank_limit, 20),
                )
                dense_rank = [
                    (_chunk_from_payload(result.id, result.payload), result.score)
                    for result in dense_results
                ]
                if trace is not None:
                    trace.append(
                        {
                            "tool": "qdrant_search",
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                            "result_count": len(dense_rank),
                            "filters": filters.as_dict(),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("hybrid_vector_search_failed", exc_info=exc)
            if trace is not None:
                trace.append(
                    {
                        "tool": "qdrant_search",
                        "error": "fallback_to_lexical",
                        "result_count": 0,
                    }
                )

    candidate_map: dict[str, PossessionChunk] = {
        chunk.chunk_id: chunk
        for ranking in (lexical, player_rank or lexical, dense_rank)
        for chunk, _score in ranking
    }
    fused_ids = reciprocal_rank_fusion(
        [
            [(chunk.chunk_id, score) for chunk, score in lexical],
            [(chunk.chunk_id, score) for chunk, score in player_rank or lexical],
            [(chunk.chunk_id, score) for chunk, score in dense_rank],
        ],
        limit=max(limit, settings.rag_rerank_limit),
    )
    if trace is not None:
        trace.append(
            {
                "tool": "rrf",
                "result_count": len(fused_ids),
                "rankings": 3 if dense_rank else 2,
            }
        )
    merged = [
        candidate_map[chunk_id] for chunk_id, _score in fused_ids if chunk_id in candidate_map
    ]

    if settings.rag_reranker_enabled and merged:
        t0 = time.perf_counter()
        merged = rerank_candidates(
            query,
            merged[:50],
            top_n=limit,
        )
        if trace is not None:
            trace.append(
                {
                    "tool": "rerank",
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "result_count": len(merged),
                }
            )
    else:
        merged = merged[:limit]
    return merged, filters
