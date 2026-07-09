"""Qdrant vector-store integration for RAG."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1024
DISTANCE = "Cosine"
GAMES_COLLECTION = "knicks_games"
POSSESSIONS_COLLECTION = "knicks_possessions"
ROSTER_COLLECTION = "knicks_roster"
QDRANT_NAMESPACE = uuid.UUID("f5af0efd-b2f7-4f7c-b0fd-09d2e5166c90")


@dataclass(frozen=True)
class QdrantSearchResult:
    id: str
    score: float
    payload: dict[str, Any]


def _collection_names() -> tuple[str, str, str]:
    settings = get_settings()
    return (
        settings.rag_qdrant_games_collection,
        settings.rag_qdrant_possessions_collection,
        settings.rag_qdrant_roster_collection,
    )


def get_qdrant_client():
    settings = get_settings()
    from qdrant_client import QdrantClient

    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout_seconds)
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        timeout=settings.qdrant_timeout_seconds,
    )


def ensure_collections(client: Any | None = None) -> None:
    """Create expected collections when missing."""
    from qdrant_client import models

    client = client or get_qdrant_client()
    existing = {item.name for item in client.get_collections().collections}
    for collection in _collection_names():
        if collection in existing:
            continue
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=get_settings().rag_qdrant_vector_size,
                distance=models.Distance.COSINE,
            ),
        )


def is_qdrant_healthy(client: Any | None = None) -> bool:
    if not get_settings().rag_qdrant_enabled:
        return False
    try:
        client = client or get_qdrant_client()
        client.get_collections()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("qdrant_health_check_failed", exc_info=exc)
        return False


def _match_any(values: set[Any] | list[Any]):
    from qdrant_client import models

    clean_values = sorted(values)
    if len(clean_values) == 1:
        return models.MatchValue(value=clean_values[0])
    return models.MatchAny(any=clean_values)


def build_qdrant_filter(filters: dict[str, Any] | None):
    """Translate retrieval filters to Qdrant payload filters."""
    if not filters:
        return None
    from qdrant_client import models

    must: list[Any] = []
    dates = set(filters.get("dates") or [])
    if dates:
        must.append(models.FieldCondition(key="date", match=_match_any(dates)))
    team_ids = set(filters.get("team_ids") or [])
    if team_ids:
        must.append(models.FieldCondition(key="team_ids", match=_match_any(team_ids)))
    periods = set(filters.get("periods") or [])
    if periods:
        should = []
        for period in sorted(periods):
            should.append(
                models.Filter(
                    must=[
                        models.FieldCondition(key="start_period", range=models.Range(lte=period)),
                        models.FieldCondition(key="end_period", range=models.Range(gte=period)),
                    ]
                )
            )
        must.append(models.Filter(should=should))
    game_ids = set(filters.get("game_ids") or [])
    if game_ids:
        must.append(models.FieldCondition(key="game_id", match=_match_any(game_ids)))
    player_names = set(filters.get("player_names") or [])
    if player_names:
        must.append(models.FieldCondition(key="player_names", match=_match_any(player_names)))
    player_ids = set(filters.get("player_ids") or [])
    if player_ids:
        must.append(models.FieldCondition(key="player_ids", match=_match_any(player_ids)))
    return models.Filter(must=must) if must else None


def upsert_points(
    collection_name: str,
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
    *,
    client: Any | None = None,
) -> int:
    """Upsert records with payloads and vectors into Qdrant."""
    if not records:
        return 0
    from qdrant_client import models

    client = client or get_qdrant_client()
    points = [
        models.PointStruct(
            id=str(qdrant_point_id(str(record["id"]))),
            vector=embedding,
            payload={**record["payload"], "chunk_id": record["id"]},
        )
        for record, embedding in zip(records, embeddings, strict=True)
    ]
    client.upsert(collection_name=collection_name, points=points)
    return len(points)


def qdrant_point_id(source_id: str) -> uuid.UUID:
    """Map local stable string IDs to Qdrant-compatible UUID point IDs."""
    return uuid.uuid5(QDRANT_NAMESPACE, source_id)


def search_collection(
    collection_name: str,
    query_embedding: list[float],
    filters: dict[str, Any] | None,
    top_k: int,
    *,
    client: Any | None = None,
) -> list[QdrantSearchResult]:
    client = client or get_qdrant_client()
    query_filter = build_qdrant_filter(filters)
    search = getattr(client, "search", None)
    if search is not None:
        hits = search(
            collection_name=collection_name,
            query_vector=query_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    else:
        hits = client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        ).points
    return [
        QdrantSearchResult(id=str(hit.id), score=float(hit.score), payload=dict(hit.payload or {}))
        for hit in hits
    ]


def search_games(
    query_embedding: list[float],
    filters: dict[str, Any] | None,
    top_k: int,
    *,
    client: Any | None = None,
) -> list[QdrantSearchResult]:
    return search_collection(
        get_settings().rag_qdrant_games_collection,
        query_embedding,
        filters,
        top_k,
        client=client,
    )


def search_possessions(
    query_embedding: list[float],
    filters: dict[str, Any] | None,
    top_k: int,
    *,
    client: Any | None = None,
) -> list[QdrantSearchResult]:
    return search_collection(
        get_settings().rag_qdrant_possessions_collection,
        query_embedding,
        filters,
        top_k,
        client=client,
    )
