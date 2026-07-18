"""Release-scoped retrieval across the immutable Qdrant archive."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.services.embeddings import embed_texts
from app.services.qdrant_client import is_qdrant_healthy, search_collection

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ArchiveEvidence:
    evidence_id: str
    collection: str
    text: str
    score: float
    metadata: dict[str, Any]


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


def _fuse(rankings: list[list[str]], *, limit: int) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
    ordered = sorted(scores, key=lambda item_id: (-scores[item_id], item_id))
    return [(item_id, scores[item_id]) for item_id in ordered[:limit]]


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
    """Search allowlisted aliases and fuse dense and lexical candidate ranks."""
    settings = get_settings()
    if not settings.rag_qdrant_enabled or not is_qdrant_healthy():
        return []
    scoped_filters = {
        key: value for key, value in filters.items() if value not in (None, [], {}, "")
    }
    scoped_filters["data_version"] = data_version
    candidates: dict[str, ArchiveEvidence] = {}
    dense_rankings: list[list[str]] = []
    query_vectors: dict[str, list[float] | str] = {}
    for query in queries[:3]:
        query_vectors[query] = (
            query
            if settings.rag_qdrant_cloud_inference
            else embed_texts([query])[0]
        )
    started = time.perf_counter()
    for collection in collections:
        alias = _collection_alias(collection)
        for query in queries[:3]:
            hits = search_collection(
                alias,
                query_vectors[query],
                scoped_filters,
                candidate_limit,
            )
            ranking: list[str] = []
            for hit in hits:
                candidate_id = f"{collection}:{hit.id}"
                ranking.append(candidate_id)
                text = str(
                    hit.payload.get("semantic_summary")
                    or hit.payload.get("text")
                    or ""
                )
                candidates[candidate_id] = ArchiveEvidence(
                    evidence_id=f"vector:{candidate_id}",
                    collection=collection,
                    text=text,
                    score=hit.score,
                    metadata=dict(hit.payload),
                )
            dense_rankings.append(ranking)
    query_tokens = _tokens(" ".join(queries))
    lexical = sorted(
        candidates,
        key=lambda candidate_id: (
            -len(query_tokens & _tokens(candidates[candidate_id].text)),
            candidate_id,
        ),
    )
    fused = _fuse([*dense_rankings, lexical], limit=limit)
    if trace is not None:
        trace.append(
            {
                "tool": "qdrant_archive_search",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": len(fused),
                "candidate_count": len(candidates),
                "collection_count": len(collections),
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
