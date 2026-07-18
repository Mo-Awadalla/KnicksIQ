"""Independent lexical and dense retrieval across the immutable archive."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.models.report import Report
from app.services.embeddings import embed_texts
from app.services.qdrant_client import get_qdrant_client, search_collection_batch
from app.services.retrieval_fusion import (
    diversify_by_game,
    weighted_reciprocal_rank_fusion,
)
from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ArchiveEvidence:
    evidence_id: str
    collection: str
    text: str
    score: float
    metadata: dict[str, Any]


def _canonical_key(collection: str, metadata: dict[str, Any], fallback: str) -> str:
    game_id = metadata.get("game_id", "archive")
    if collection == "games":
        source_id = game_id
    elif collection == "box_scores":
        source_id = (
            metadata.get("source_row_id")
            or tuple(metadata.get("player_ids") or [])
            or tuple(metadata.get("team_ids") or [])
            or fallback
        )
    elif collection == "reports":
        source_id = metadata.get("report_id") or metadata.get("chunk_id") or fallback
    else:
        source_id = (
            metadata.get("sequence_id")
            or metadata.get("chunk_id")
            or metadata.get("source_row_id")
            or fallback
        )
    return f"{collection}:{game_id}:{source_id}"


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 2}


def _collection_alias(kind: str) -> str:
    settings = get_settings()
    return {
        "games": settings.rag_qdrant_games_collection,
        "box_scores": settings.rag_qdrant_box_scores_collection,
        "reports": settings.rag_qdrant_reports_collection,
        "possessions": settings.rag_qdrant_possessions_collection,
    }[kind]


def search_archive_vectors(
    *,
    queries: list[str],
    collections: list[str],
    filters: dict[str, Any],
    data_version: str,
    limit: int,
    candidate_limit: int,
    trace: list[dict[str, Any]] | None = None,
) -> list[ArchiveEvidence]:
    """Search allowlisted aliases. This function performs dense retrieval only."""
    settings = get_settings()
    if not settings.rag_qdrant_enabled:
        return []
    scoped_filters = {
        key: value for key, value in filters.items() if value not in (None, [], {}, "")
    }
    scoped_filters["data_version"] = data_version
    candidates: dict[str, ArchiveEvidence] = {}
    dense_rankings: list[list[str]] = []
    selected_queries = list(dict.fromkeys(queries[:3]))
    query_vectors: dict[str, list[float] | str] = {}
    for query in selected_queries:
        query_vectors[query] = (
            query if settings.rag_qdrant_cloud_inference else embed_texts([query])[0]
        )
    started = time.perf_counter()
    client = get_qdrant_client()
    for collection in collections:
        alias = _collection_alias(collection)
        result_batches = search_collection_batch(
            alias,
            [query_vectors[query] for query in selected_queries],
            scoped_filters,
            candidate_limit,
            client=client,
        )
        for hits in result_batches:
            ranking: list[str] = []
            for hit in hits:
                candidate_id = f"{collection}:{hit.id}"
                ranking.append(candidate_id)
                text = str(hit.payload.get("semantic_summary") or hit.payload.get("text") or "")
                candidates[candidate_id] = ArchiveEvidence(
                    evidence_id=f"vector:{candidate_id}",
                    collection=collection,
                    text=text,
                    score=hit.score,
                    metadata=dict(hit.payload),
                )
            dense_rankings.append(ranking)
    fused = [
        (item.key, item.score)
        for item in weighted_reciprocal_rank_fusion(
            [("dense", ranking, 1.0) for ranking in dense_rankings],
            limit=limit,
            k=getattr(settings, "rag_rrf_k", 60),
        )
    ]
    if trace is not None:
        trace.append(
            {
                "tool": "qdrant_archive_search",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": len(fused),
                "candidate_count": len(candidates),
                "collection_count": len(collections),
                "retrieval_source": "dense",
            }
        )
    return [
        ArchiveEvidence(
            evidence_id=candidates[candidate_id].evidence_id,
            collection=candidates[candidate_id].collection,
            text=candidates[candidate_id].text,
            score=score,
            metadata=candidates[candidate_id].metadata,
        )
        for candidate_id, score in fused
    ]


def _clean_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, [], {}, "")}


def _game_filter_clauses(filters: dict[str, Any]) -> list[Any]:
    clauses: list[Any] = []
    if filters.get("dates"):
        clauses.append(Game.game_date.in_([date.fromisoformat(item) for item in filters["dates"]]))
    if filters.get("game_ids"):
        clauses.append(Game.id.in_(filters["game_ids"]))
    if filters.get("season_types"):
        clauses.append(Game.season_type.in_(filters["season_types"]))
    team_ids = set(filters.get("team_ids") or [])
    if team_ids:
        clauses.append(or_(Game.home_team_id.in_(team_ids), Game.away_team_id.in_(team_ids)))
    return clauses


def _lexical_match(db: AsyncSession, text_expression: Any, query: str) -> tuple[Any, Any]:
    """Return a backend-appropriate match predicate and rank expression."""
    if db.bind and db.bind.dialect.name == "postgresql":
        vector = func.to_tsvector("simple", func.coalesce(text_expression, ""))
        tsquery = func.websearch_to_tsquery("simple", query)
        return vector.op("@@")(tsquery), func.ts_rank_cd(vector, tsquery)
    lowered = query.lower()
    tokens = sorted(_tokens(lowered))
    if not tokens:
        return literal(True), literal(0.0)
    predicates = [func.lower(text_expression).contains(token) for token in tokens]
    rank = sum(
        (case((func.lower(text_expression).contains(token), 1), else_=0) for token in tokens),
        literal(0),
    )
    return or_(*predicates), rank


async def search_archive_lexical(
    db: AsyncSession,
    *,
    query: str,
    collections: list[str],
    filters: dict[str, Any],
    data_version: str,
    limit: int,
    trace: list[dict[str, Any]] | None = None,
) -> list[ArchiveEvidence]:
    """Search PostgreSQL independently of Qdrant, always scoped to one release."""
    started = time.perf_counter()
    clean = _clean_filters(filters)
    release_id = (
        await db.execute(
            select(DatasetRelease.id).where(
                DatasetRelease.version == data_version,
                DatasetRelease.validation_passed.is_(True),
            )
        )
    ).scalar_one_or_none()
    if release_id is None and not get_settings().test_mode:
        return []

    game_clauses = _game_filter_clauses(clean)
    evidence: list[ArchiveEvidence] = []

    if "games" in collections:
        text = (
            Game.away_team_id
            + " "
            + cast(Game.away_score, String)
            + " at "
            + Game.home_team_id
            + " "
            + cast(Game.home_score, String)
            + " "
            + func.coalesce(Game.game_label, "")
        )
        match, rank = _lexical_match(db, text, query)
        stmt = select(Game, text.label("text"), rank.label("rank")).where(match, *game_clauses)
        if release_id is not None:
            stmt = stmt.where(Game.release_id == release_id)
        for game, value, score in (await db.execute(stmt.order_by(rank.desc()).limit(limit))).all():
            metadata = {
                "game_id": game.id,
                "date": str(game.game_date),
                "team_ids": [game.home_team_id, game.away_team_id],
                "season_type": game.season_type,
                "data_version": data_version,
                "source_row_id": game.id,
                "retrieval_sources": ["lexical"],
            }
            evidence.append(
                ArchiveEvidence(
                    f"lexical:games:{game.id}",
                    "games",
                    str(value),
                    float(score or 0),
                    metadata,
                )
            )

    if "reports" in collections:
        text = Report.title + " " + Report.summary + " " + Report.turning_point
        match, rank = _lexical_match(db, text, query)
        stmt = (
            select(Report, Game, text.label("text"), rank.label("rank"))
            .join(Game, Game.id == Report.game_id)
            .where(Report.reviewed.is_(True), match, *game_clauses)
        )
        if release_id is not None:
            stmt = stmt.where(Report.release_id == release_id, Game.release_id == release_id)
        for report, game, value, score in (
            await db.execute(stmt.order_by(rank.desc()).limit(limit))
        ).all():
            metadata = {
                "game_id": game.id,
                "report_id": report.id,
                "date": str(game.game_date),
                "team_ids": [game.home_team_id, game.away_team_id],
                "season_type": game.season_type,
                "data_version": data_version,
                "retrieval_sources": ["lexical"],
            }
            evidence.append(
                ArchiveEvidence(
                    f"lexical:reports:{report.id}",
                    "reports",
                    str(value),
                    float(score or 0),
                    metadata,
                )
            )

    if "box_scores" in collections:
        team_text = (
            TeamGameStat.team_id
            + " "
            + cast(TeamGameStat.points, String)
            + " points "
            + cast(TeamGameStat.rebounds, String)
            + " rebounds "
            + cast(TeamGameStat.assists, String)
            + " assists "
            + cast(TeamGameStat.turnovers, String)
            + " turnovers"
        )
        team_match, team_rank = _lexical_match(db, team_text, query)
        team_stmt = (
            select(
                TeamGameStat,
                Game,
                team_text.label("text"),
                team_rank.label("rank"),
            )
            .join(Game, Game.id == TeamGameStat.game_id)
            .where(team_match, *game_clauses)
        )
        if release_id is not None:
            team_stmt = team_stmt.where(
                TeamGameStat.release_id == release_id,
                Game.release_id == release_id,
            )
        for stat, game, value, score in (
            await db.execute(team_stmt.order_by(team_rank.desc()).limit(limit))
        ).all():
            metadata = {
                "game_id": game.id,
                "source_row_id": f"team:{stat.id}",
                "date": str(game.game_date),
                "team_ids": [stat.team_id],
                "season_type": game.season_type,
                "data_version": data_version,
                "retrieval_sources": ["lexical"],
            }
            evidence.append(
                ArchiveEvidence(
                    f"lexical:box_scores:team:{stat.id}",
                    "box_scores",
                    str(value),
                    float(score or 0),
                    metadata,
                )
            )

        player_text = (
            Player.full_name
            + " "
            + cast(PlayerGameStat.points, String)
            + " points "
            + cast(PlayerGameStat.rebounds, String)
            + " rebounds "
            + cast(PlayerGameStat.assists, String)
            + " assists"
        )
        match, rank = _lexical_match(db, player_text, query)
        stmt = (
            select(PlayerGameStat, Player, Game, player_text.label("text"), rank.label("rank"))
            .join(Player, Player.id == PlayerGameStat.player_id)
            .join(Game, Game.id == PlayerGameStat.game_id)
            .where(match, *game_clauses)
        )
        if clean.get("player_ids"):
            stmt = stmt.where(PlayerGameStat.player_id.in_(clean["player_ids"]))
        if release_id is not None:
            stmt = stmt.where(
                PlayerGameStat.release_id == release_id,
                Game.release_id == release_id,
            )
        for stat, player, game, value, score in (
            await db.execute(stmt.order_by(rank.desc()).limit(limit))
        ).all():
            metadata = {
                "game_id": game.id,
                "source_row_id": stat.id,
                "date": str(game.game_date),
                "team_ids": [stat.team_id],
                "player_ids": [stat.player_id],
                "player_names": [player.full_name],
                "season_type": game.season_type,
                "data_version": data_version,
                "retrieval_sources": ["lexical"],
            }
            evidence.append(
                ArchiveEvidence(
                    f"lexical:box_scores:{stat.id}",
                    "box_scores",
                    str(value),
                    float(score or 0),
                    metadata,
                )
            )

    if "possessions" in collections:
        text = func.coalesce(GameEvent.description, "")
        match, rank = _lexical_match(db, text, query)
        stmt = (
            select(GameEvent, Game, text.label("text"), rank.label("rank"))
            .join(Game, Game.id == GameEvent.game_id)
            .where(match, *game_clauses)
        )
        if clean.get("periods"):
            stmt = stmt.where(GameEvent.period.in_(clean["periods"]))
        if clean.get("player_ids"):
            stmt = stmt.where(GameEvent.player_id.in_(clean["player_ids"]))
        if release_id is not None:
            stmt = stmt.where(Game.release_id == release_id)
        for event, game, value, score in (
            await db.execute(stmt.order_by(rank.desc()).limit(limit))
        ).all():
            metadata = {
                "game_id": game.id,
                "source_row_id": event.id,
                "sequence_id": event.sequence,
                "date": str(game.game_date),
                "team_ids": [event.team_id] if event.team_id else [],
                "player_ids": [event.player_id] if event.player_id else [],
                "start_period": event.period,
                "end_period": event.period,
                "data_version": data_version,
                "retrieval_sources": ["lexical"],
            }
            evidence.append(
                ArchiveEvidence(
                    f"lexical:possessions:{event.id}",
                    "possessions",
                    str(value),
                    float(score or 0),
                    metadata,
                )
            )

    evidence.sort(key=lambda item: (-item.score, item.evidence_id))
    result = evidence[:limit]
    if trace is not None:
        trace.append(
            {
                "tool": "postgres_lexical_search",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": len(result),
                "retrieval_source": "lexical",
                "data_version": data_version,
            }
        )
    return result


def fuse_archive_evidence(
    lexical: list[ArchiveEvidence],
    dense: list[ArchiveEvidence],
    *,
    limit: int,
    max_per_game: int | None = None,
    filters: dict[str, Any] | None = None,
    weighted: bool = True,
) -> list[ArchiveEvidence]:
    """Deduplicate canonical evidence and apply configurable weighted RRF."""
    settings = get_settings()
    candidates: dict[str, ArchiveEvidence] = {}
    rankings: list[tuple[str, list[str], float]] = []
    component_ranks: dict[str, dict[str, int]] = {}
    for source, items, weight in (
        ("lexical", lexical, getattr(settings, "rag_lexical_weight", 1.25)),
        ("dense", dense, getattr(settings, "rag_dense_weight", 1.0)),
    ):
        if not weighted:
            weight = 1.0
        ranking: list[str] = []
        for item in items:
            key = _canonical_key(item.collection, item.metadata, item.evidence_id)
            ranking.append(key)
            existing = candidates.get(key)
            sources = sorted(
                set((existing.metadata.get("retrieval_sources", []) if existing else []) + [source])
            )
            preferred = (
                item if existing is None or len(item.text) > len(existing.text) else existing
            )
            candidates[key] = ArchiveEvidence(
                evidence_id=preferred.evidence_id,
                collection=preferred.collection,
                text=preferred.text,
                score=preferred.score,
                metadata={**preferred.metadata, "retrieval_sources": sources},
            )
        rankings.append((source, ranking, weight))
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            component_ranks.setdefault(key, {})[source] = rank
    fused = weighted_reciprocal_rank_fusion(
        rankings,
        limit=getattr(settings, "rag_fused_candidate_limit", 20),
        k=getattr(settings, "rag_rrf_k", 60),
    )
    scoped_filters = _clean_filters(filters or {})
    ranked: list[ArchiveEvidence] = []
    for item in fused:
        candidate = candidates[item.key]
        exact_fields: list[str] = []
        if scoped_filters.get("game_ids") and candidate.metadata.get("game_id") in set(
            scoped_filters["game_ids"]
        ):
            exact_fields.append("game_id")
        if scoped_filters.get("dates") and candidate.metadata.get("date") in set(
            scoped_filters["dates"]
        ):
            exact_fields.append("date")
        for field in ("team_ids", "player_ids"):
            if scoped_filters.get(field) and set(scoped_filters[field]) & set(
                candidate.metadata.get(field) or []
            ):
                exact_fields.append(field)
        if scoped_filters.get("periods"):
            start = int(candidate.metadata.get("start_period") or 0)
            end = int(candidate.metadata.get("end_period") or start)
            if any(start <= int(period) <= end for period in scoped_filters["periods"]):
                exact_fields.append("periods")
        score = item.score
        if weighted:
            score *= 1 + getattr(settings, "rag_exact_match_boost", 0.25) * len(exact_fields)
            score *= getattr(settings, "rag_collection_weights", {}).get(
                candidate.collection,
                1.0,
            )
        ranked.append(
            ArchiveEvidence(
                evidence_id=candidates[item.key].evidence_id,
                collection=candidates[item.key].collection,
                text=candidates[item.key].text,
                score=score,
                metadata={
                    **candidates[item.key].metadata,
                    "exact_match_fields": exact_fields,
                    "fusion_components": [
                        {
                            "source": component.source,
                            "rank": component.rank,
                            "weight": component.weight,
                            "contribution": component.contribution,
                        }
                        for component in item.components
                    ],
                    "component_ranks": component_ranks[item.key],
                },
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.evidence_id))
    return diversify_by_game(
        ranked,
        limit=limit,
        max_per_game=max_per_game,
        game_id_getter=lambda item: item.metadata.get("game_id"),
    )
