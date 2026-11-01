"""Independent lexical and dense retrieval across the immutable archive.

Dense search reads the allowlisted Qdrant aliases; lexical search delegates its
per-collection statements to :mod:`app.services.archive_lexical_sql` and keeps
the ordering, limit and release scope here. Fusion is weighted RRF with
diversification, and the retrieval trace records the ordering actually produced.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.core.config import get_settings
from app.models.dataset_release import DatasetRelease
from app.services import archive_lexical_sql as lexical
from app.services.archive_clock import GameMoment
from app.services.archive_documents import ArchiveDocument, Collection
from app.services.archive_evidence import ArchiveEvidence as ArchiveEvidence
from app.services.archive_evidence import _canonical_key
from app.services.archive_lexical_sql import clean_filters, game_filter_clauses
from app.services.embeddings import embed_texts
from app.services.qdrant_client import get_qdrant_client, search_collection_batch
from app.services.release_bundle import canonical_json
from app.services.retrieval_fusion import (
    diversify_by_game,
    weighted_reciprocal_rank_fusion,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
                document_id = hit.payload.get("chunk_id")
                if not isinstance(document_id, str) or not document_id:
                    raise ValueError("Dense hit has no indexed document identity")
                candidates[candidate_id] = ArchiveDocument(
                    document_id, cast(Collection, collection), hit.payload
                ).evidence(
                    score=hit.score,
                    source="dense",
                    evidence_id=f"vector:{candidate_id}",
                    point_id=str(hit.id),
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
    clean = clean_filters(filters)
    moment = GameMoment.from_filter(clean.get("event_clock"))
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

    clauses = game_filter_clauses(clean)
    scope = {
        "query": query,
        "game_clauses": clauses,
        "release_id": release_id,
        "limit": limit,
        "data_version": data_version,
    }
    evidence: list[ArchiveEvidence] = []
    if "games" in collections and moment is None:
        evidence.extend(await lexical.game_evidence(db, **scope))
    if "reports" in collections and moment is None:
        evidence.extend(await lexical.report_evidence(db, **scope))
    if "box_scores" in collections and moment is None:
        evidence.extend(await lexical.team_stat_evidence(db, **scope))
        evidence.extend(
            await lexical.player_stat_evidence(db, **scope, player_ids=clean.get("player_ids"))
        )
    if "possessions" in collections:
        evidence.extend(
            await lexical.possession_evidence(
                db,
                **scope,
                periods=clean.get("periods"),
                player_ids=clean.get("player_ids"),
                moment=moment,
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


@dataclass(frozen=True)
class RankedEvidence:
    """One retrieval result with the identity a reviewer needs to map it.

    Runtime ids stay runtime ids. Evaluation maps them through the recorded local
    mapping instead of assuming canonical and runtime ids agree.
    """

    evidence_id: str
    collection: str
    game_id: int | None
    player_ids: tuple[int, ...]
    team_ids: tuple[str, ...]
    source_row_id: int | str | None
    sequence_id: str | None
    score: float
    rank: int
    document_id: str | None = None
    point_id: str | None = None
    payload_sha256: str | None = None

    def as_trace(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "collection": self.collection,
            "game_id": self.game_id,
            "player_ids": list(self.player_ids),
            "team_ids": list(self.team_ids),
            "source_row_id": self.source_row_id,
            "sequence_id": self.sequence_id,
            "document_id": self.document_id,
            "point_id": self.point_id,
            "payload_sha256": self.payload_sha256,
            "score": self.score,
            "rank": self.rank,
        }


def ranked_evidence(items: list[ArchiveEvidence]) -> tuple[RankedEvidence, ...]:
    """Freeze a ranked list, keeping its actual order and length."""
    frozen: list[RankedEvidence] = []
    for rank, item in enumerate(items, start=1):
        metadata = item.metadata
        player_ids = metadata.get("player_ids") or []
        document_payload = metadata.get("document_payload")
        if document_payload is not None:
            actual_hash = hashlib.sha256(canonical_json(document_payload)).hexdigest()
            if actual_hash != metadata.get("payload_sha256"):
                raise ValueError("Retrieved document payload digest changed")
        frozen.append(
            RankedEvidence(
                evidence_id=item.evidence_id,
                collection=item.collection,
                game_id=metadata.get("game_id"),
                player_ids=tuple(player_ids),
                team_ids=tuple(metadata.get("team_ids") or []),
                source_row_id=metadata.get("source_row_id") or metadata.get("report_id"),
                sequence_id=(
                    str(metadata["sequence_id"])
                    if metadata.get("sequence_id") is not None
                    else None
                ),
                score=float(item.score),
                rank=rank,
                document_id=metadata.get("document_id"),
                point_id=metadata.get("point_id"),
                payload_sha256=metadata.get("payload_sha256"),
            )
        )
    return tuple(frozen)


@dataclass(frozen=True)
class RetrievalTrace:
    """Ordering actually produced at the retrieval/fusion boundary for one request.

    ``candidates`` is the fused ranking before the caller's final selection; it may
    itself be truncated by the fusion candidate limit, which is recorded.
    ``selected`` is what the caller actually emitted, whatever its length, so the
    evaluation can take its own top-5 cut without the trace fabricating one.
    """

    request_id: str
    data_version: str
    lexical: tuple[RankedEvidence, ...]
    dense: tuple[RankedEvidence, ...]
    candidates: tuple[RankedEvidence, ...]
    selected: tuple[RankedEvidence, ...]
    errors: tuple[str, ...]
    latency_ms: int
    candidate_limit: int | None
    candidate_limit_applied: bool
    lexical_limit: int | None = None
    dense_limit: int | None = None
    dense_status: Literal["ok", "failed", "disabled"] = "disabled"

    def as_trace(self) -> dict[str, Any]:
        return {
            "stage": "retrieval",
            "tool": "archive_retrieval",
            "kind": "retrieval_trace",
            "request_id": self.request_id,
            "data_version": self.data_version,
            "latency_ms": self.latency_ms,
            "errors": list(self.errors),
            "candidate_limit": self.candidate_limit,
            "candidate_limit_applied": self.candidate_limit_applied,
            "lexical_limit": self.lexical_limit,
            "dense_limit": self.dense_limit,
            "dense_status": self.dense_status,
            "lexical": [item.as_trace() for item in self.lexical],
            "dense": [item.as_trace() for item in self.dense],
            "candidates": [item.as_trace() for item in self.candidates],
            "selected": [item.as_trace() for item in self.selected],
        }


def fuse_archive_evidence(
    lexical: list[ArchiveEvidence],
    dense: list[ArchiveEvidence],
    *,
    limit: int,
    max_per_game: int | None = None,
    filters: dict[str, Any] | None = None,
    weighted: bool = True,
    trace: list[RetrievalTrace] | None = None,
    request_id: str | None = None,
    data_version: str | None = None,
    errors: tuple[str, ...] = (),
    dense_status: Literal["ok", "failed", "disabled"] = "disabled",
    lexical_limit: int | None = None,
    dense_limit: int | None = None,
) -> list[ArchiveEvidence]:
    """Deduplicate canonical evidence and apply configurable weighted RRF.

    When ``trace`` is given, one correlated :class:`RetrievalTrace` describing the actual
    lexical, dense, fused and emitted ordering is appended. A trace without the request
    identity and release it belongs to is rejected rather than recorded anonymously.
    """
    if trace is not None and not (request_id and data_version):
        raise ValueError("A retrieval trace requires the actual request_id and data_version")
    started = time.perf_counter()
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
    scoped_filters = clean_filters(filters or {})
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
    selected = diversify_by_game(
        ranked,
        limit=limit,
        max_per_game=max_per_game,
        game_id_getter=lambda item: item.metadata.get("game_id"),
    )
    if trace is not None and request_id and data_version:
        trace.append(
            RetrievalTrace(
                request_id=request_id,
                data_version=data_version,
                lexical=ranked_evidence(lexical),
                dense=ranked_evidence(dense),
                candidates=ranked_evidence(ranked),
                selected=ranked_evidence(selected),
                errors=tuple(errors),
                latency_ms=int((time.perf_counter() - started) * 1000),
                candidate_limit=getattr(settings, "rag_fused_candidate_limit", 20),
                candidate_limit_applied=True,
                lexical_limit=lexical_limit,
                dense_limit=dense_limit,
                dense_status=dense_status,
            )
        )
    return selected
