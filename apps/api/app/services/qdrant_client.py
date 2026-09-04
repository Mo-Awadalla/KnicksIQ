"""Qdrant vector-store integration for RAG."""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 384
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


def _collection_names() -> tuple[str, ...]:
    settings = get_settings()
    return (
        settings.rag_qdrant_games_collection,
        settings.rag_qdrant_possessions_collection,
        settings.rag_qdrant_roster_collection,
        settings.rag_qdrant_box_scores_collection,
        settings.rag_qdrant_reports_collection,
    )


@lru_cache(maxsize=8)
def _cached_qdrant_client(
    url: str | None,
    api_key: str | None,
    cloud_inference: bool,
    timeout_seconds: int,
    host: str,
    port: int,
):
    from qdrant_client import QdrantClient

    if url:
        return QdrantClient(
            url=url,
            api_key=api_key,
            cloud_inference=cloud_inference,
            timeout=timeout_seconds,
        )
    return QdrantClient(
        host=host,
        port=port,
        timeout=timeout_seconds,
    )


def get_qdrant_client():
    settings = get_settings()
    return _cached_qdrant_client(
        settings.qdrant_url,
        settings.qdrant_api_key,
        settings.rag_qdrant_cloud_inference,
        settings.qdrant_timeout_seconds,
        settings.qdrant_host,
        settings.qdrant_port,
    )


def ensure_collections(client: Any | None = None) -> None:
    """Create expected collections when missing."""
    resolved: Any = client or get_qdrant_client()
    existing = {item.name for item in resolved.get_collections().collections}
    for collection in _collection_names():
        if collection in existing:
            continue
        create_collection(collection, client=resolved)


def create_collection(collection_name: str, *, client: Any | None = None) -> None:
    """Create a collection with the configured dense-vector schema."""
    from qdrant_client import models

    resolved: Any = client or get_qdrant_client()
    resolved.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=get_settings().rag_qdrant_vector_size,
            distance=models.Distance.COSINE,
        ),
    )
    create_payload_indexes(collection_name, client=resolved)


def create_payload_indexes(collection_name: str, *, client: Any | None = None) -> None:
    """Create indexes required by Qdrant Cloud for strict metadata filters."""
    from qdrant_client import models

    resolved: Any = client or get_qdrant_client()
    schemas = {
        "data_version": models.PayloadSchemaType.KEYWORD,
        "date": models.PayloadSchemaType.KEYWORD,
        "team_ids": models.PayloadSchemaType.KEYWORD,
        "season_type": models.PayloadSchemaType.KEYWORD,
        "game_id": models.PayloadSchemaType.INTEGER,
        "player_ids": models.PayloadSchemaType.INTEGER,
        "player_names": models.PayloadSchemaType.KEYWORD,
        "start_period": models.PayloadSchemaType.INTEGER,
        "end_period": models.PayloadSchemaType.INTEGER,
    }
    for field_name, field_schema in schemas.items():
        resolved.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


def recreate_collection(collection_name: str, *, client: Any | None = None) -> None:
    """Reset one collection without touching the rest of the local Qdrant store."""
    resolved: Any = client or get_qdrant_client()
    recreate = getattr(resolved, "recreate_collection", None)
    if recreate is not None:
        from qdrant_client import models

        recreate(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=get_settings().rag_qdrant_vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        create_payload_indexes(collection_name, client=resolved)
        return

    existing = {item.name for item in resolved.get_collections().collections}
    if collection_name in existing:
        resolved.delete_collection(collection_name=collection_name)
    create_collection(collection_name, client=resolved)


_health_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retrieval-health")
_health_lock = Lock()
_health_future: Any = None
_health_checked_at = 0.0
_health_result = False


def inspect_retrieval_targets(client: Any | None = None) -> dict[str, Any]:
    """Read usable dense targets; connectivity alone is insufficient."""
    settings = get_settings()
    resolved = client or get_qdrant_client()
    targets = (
        settings.rag_qdrant_games_collection,
        settings.rag_qdrant_possessions_collection,
        settings.rag_qdrant_box_scores_collection,
        settings.rag_qdrant_reports_collection,
    )
    aliases = {item.alias_name: item.collection_name for item in resolved.get_aliases().aliases}
    result: dict[str, Any] = {"aliases": aliases, "targets": {}, "usable": True}
    for target in targets:
        info = resolved.get_collection(target)
        vector = info.config.params.vectors
        count = resolved.count(collection_name=target, exact=True).count
        points, _ = resolved.scroll(collection_name=target, limit=1, with_payload=True)
        payload = (points[0].payload or {}) if points else {}
        usable = (
            getattr(vector, "size", None) == settings.rag_qdrant_vector_size
            and str(getattr(vector, "distance", "")).lower() == "cosine"
            and count > 0
            and bool(payload.get("data_version"))
        )
        result["targets"][target] = {
            "physical_collection": aliases.get(target, target),
            "points": count,
            "vector_size": getattr(vector, "size", None),
            "distance": str(getattr(vector, "distance", "")),
            "sample_data_version": payload.get("data_version"),
            "usable": usable,
        }
        result["usable"] = result["usable"] and usable
    return result


def validate_candidate_collection(collection: str, data_version: str, expected_count: int) -> None:
    """Verify stored counts and release isolation, not only write acknowledgements."""
    from qdrant_client import models

    client = get_qdrant_client()
    info = client.get_collection(collection)
    vector = info.config.params.vectors
    if (
        getattr(vector, "size", None) != get_settings().rag_qdrant_vector_size
        or str(getattr(vector, "distance", "")).lower() != "cosine"
    ):
        raise RuntimeError("Candidate vector configuration mismatch")
    count = client.count(collection_name=collection, exact=True).count
    scoped = client.count(
        collection_name=collection,
        exact=True,
        count_filter=build_qdrant_filter({"data_version": data_version}),
    ).count
    other = client.count(
        collection_name=collection,
        exact=True,
        count_filter=models.Filter(
            must_not=[
                models.FieldCondition(
                    key="data_version",
                    match=models.MatchValue(value=data_version),
                )
            ]
        ),
    ).count
    if expected_count <= 0 or count != expected_count or scoped != count or other:
        raise RuntimeError("Candidate stored count or release payload mismatch")


def ensure_candidate_not_serving(collection: str) -> None:
    """Never reset a physical collection that is reachable through a live alias."""
    if any(
        alias.collection_name == collection for alias in get_qdrant_client().get_aliases().aliases
    ):
        raise RuntimeError("Candidate collection is already serving an alias; use a new version")


def is_qdrant_healthy(client: Any | None = None) -> bool:
    """Cache usable-target checks for 30s; cap caller waiting at 250ms.

    A single shared in-flight probe prevents request-time probe amplification.
    Optional retrieval failure never prevents deterministic archive answers.
    """
    global _health_future, _health_checked_at, _health_result
    if not get_settings().rag_qdrant_enabled:
        return False
    with _health_lock:
        if client is None and time.monotonic() - _health_checked_at < 30:
            return _health_result
        if _health_future is None:
            _health_future = _health_pool.submit(inspect_retrieval_targets, client)
        future = _health_future
    try:
        result = bool(future.result(timeout=0.25)["usable"])
    except TimeoutError:
        return False
    except Exception:
        result = False
    with _health_lock:
        _health_result = result
        _health_checked_at = time.monotonic()
        _health_future = None
    return result


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
    data_version = filters.get("data_version")
    if data_version:
        must.append(
            models.FieldCondition(key="data_version", match=models.MatchValue(value=data_version))
        )
    season_types = set(filters.get("season_types") or [])
    if season_types:
        must.append(models.FieldCondition(key="season_type", match=_match_any(season_types)))
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
    embeddings: list[list[float]] | None = None,
    *,
    documents: list[str] | None = None,
    client: Any | None = None,
) -> int:
    """Upsert records with payloads and vectors into Qdrant."""
    if not records:
        return 0
    from qdrant_client import models

    resolved: Any = client or get_qdrant_client()
    use_cloud_inference = get_settings().rag_qdrant_cloud_inference
    if use_cloud_inference:
        if documents is None or len(documents) != len(records):
            raise ValueError("Cloud inference requires one source document per record")
        vectors: list[Any] = [
            models.Document(text=document, model=get_settings().rag_embedding_model)
            for document in documents
        ]
    else:
        if embeddings is None or len(embeddings) != len(records):
            raise ValueError("Local indexing requires one embedding per record")
        vectors = embeddings
    points = [
        models.PointStruct(
            id=str(qdrant_point_id(str(record["id"]))),
            vector=embedding,
            payload={**record["payload"], "chunk_id": record["id"]},
        )
        for record, embedding in zip(records, vectors, strict=True)
    ]
    resolved.upsert(collection_name=collection_name, points=points)
    return len(points)


def qdrant_point_id(source_id: str) -> uuid.UUID:
    """Map local stable string IDs to Qdrant-compatible UUID point IDs."""
    return uuid.uuid5(QDRANT_NAMESPACE, source_id)


def search_collection(
    collection_name: str,
    query_embedding: list[float] | str,
    filters: dict[str, Any] | None,
    top_k: int,
    *,
    client: Any | None = None,
) -> list[QdrantSearchResult]:
    resolved: Any = client or get_qdrant_client()
    query_filter = build_qdrant_filter(filters)
    if isinstance(query_embedding, str):
        from qdrant_client import models

        hits = resolved.query_points(
            collection_name=collection_name,
            query=models.Document(
                text=query_embedding,
                model=get_settings().rag_embedding_model,
            ),
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        ).points
        return [
            QdrantSearchResult(
                id=str(hit.id), score=float(hit.score), payload=dict(hit.payload or {})
            )
            for hit in hits
        ]
    search = getattr(resolved, "search", None)
    if search is not None:
        hits = search(
            collection_name=collection_name,
            query_vector=query_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    else:
        hits = resolved.query_points(
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


def search_collection_batch(
    collection_name: str,
    query_embeddings: list[list[float] | str],
    filters: dict[str, Any] | None,
    top_k: int,
    *,
    client: Any | None = None,
) -> list[list[QdrantSearchResult]]:
    """Batch multiple searches against one collection into one network request."""
    if not query_embeddings:
        return []
    from qdrant_client import models

    resolved: Any = client or get_qdrant_client()
    query_filter = build_qdrant_filter(filters)
    requests = [
        models.QueryRequest(
            query=(
                models.Document(text=query, model=get_settings().rag_embedding_model)
                if isinstance(query, str)
                else query
            ),
            filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        for query in query_embeddings
    ]
    responses = resolved.query_batch_points(
        collection_name=collection_name,
        requests=requests,
    )
    return [
        [
            QdrantSearchResult(
                id=str(hit.id),
                score=float(hit.score),
                payload=dict(hit.payload or {}),
            )
            for hit in response.points
        ]
        for response in responses
    ]


def versioned_collection(alias: str, data_version: str) -> str:
    safe_version = "".join(char if char.isalnum() else "_" for char in data_version)
    return f"{alias}__{safe_version}"


def switch_alias(alias: str, collection_name: str, *, client: Any | None = None) -> None:
    """Atomically point one stable read alias at a validated physical collection."""
    switch_aliases({alias: collection_name}, client=client)


def switch_aliases(aliases: dict[str, str], *, client: Any | None = None) -> None:
    """Promote every release collection in one Qdrant alias transaction."""
    from qdrant_client import models

    resolved: Any = client or get_qdrant_client()
    existing = {item.alias_name for item in resolved.get_aliases().aliases}
    collections = {item.name for item in resolved.get_collections().collections}
    # Older deployments wrote directly to stable collection names. Once every
    # versioned replacement has been built and validated, remove those legacy
    # collections so the same stable names can become aliases. Qdrant remains
    # optional during this one-time migration and SQL/lexical retrieval stays up.
    for alias, collection_name in aliases.items():
        if alias in collections and alias != collection_name:
            resolved.delete_collection(collection_name=alias)
    operations: list[Any] = []
    for alias, collection_name in sorted(aliases.items()):
        if alias in existing:
            operations.append(
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(collection_name=collection_name, alias_name=alias)
            )
        )
    resolved.update_collection_aliases(change_aliases_operations=operations)


def search_games(
    query_embedding: list[float] | str,
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
    query_embedding: list[float] | str,
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
