"""Release-scoped vector retrieval behavior."""

from __future__ import annotations

from app.services import archive_retrieval
from app.services.archive_retrieval import search_archive_vectors
from app.services.qdrant_client import (
    QdrantSearchResult,
    build_qdrant_filter,
    create_payload_indexes,
)


def test_archive_vector_search_injects_active_release_scope(monkeypatch):
    calls = []

    class Settings:
        rag_qdrant_enabled = True
        rag_qdrant_cloud_inference = True
        rag_qdrant_games_collection = "knicks_games"
        rag_qdrant_reports_collection = "knicks_reports"
        rag_qdrant_box_scores_collection = "knicks_box_scores"
        rag_qdrant_possessions_collection = "knicks_possessions"

    def search(collection, query, filters, top_k):
        calls.append((collection, query, filters, top_k))
        return [
            QdrantSearchResult(
                id=f"{collection}:1",
                score=0.9,
                payload={"semantic_summary": f"{collection} Toronto archive fact"},
            )
        ]

    monkeypatch.setattr(archive_retrieval, "get_settings", lambda: Settings())
    monkeypatch.setattr(archive_retrieval, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(archive_retrieval, "search_collection", search)

    results = search_archive_vectors(
        queries=["Toronto turning points"],
        collections=["games", "reports"],
        filters={"team_ids": ["TOR"]},
        data_version="release-2025-26",
        limit=5,
        candidate_limit=20,
    )

    assert {call[0] for call in calls} == {"knicks_games", "knicks_reports"}
    assert all(call[1] == "Toronto turning points" for call in calls)
    assert all(call[2]["data_version"] == "release-2025-26" for call in calls)
    assert all(call[2]["team_ids"] == ["TOR"] for call in calls)
    assert all(call[3] == 20 for call in calls)
    assert len(results) == 2


def test_qdrant_filter_includes_selected_season_types():
    query_filter = build_qdrant_filter({"season_types": ["playoffs"]})

    assert query_filter is not None
    payload = query_filter.model_dump()
    assert any(
        condition.get("key") == "season_type"
        for condition in payload.get("must") or []
        if isinstance(condition, dict)
    )


def test_qdrant_collections_index_every_filterable_payload_field():
    indexed = []

    class Client:
        def create_payload_index(self, **kwargs):
            indexed.append(kwargs)

    create_payload_indexes("knicks_test", client=Client())

    assert {item["field_name"] for item in indexed} == {
        "data_version",
        "date",
        "team_ids",
        "season_type",
        "game_id",
        "player_ids",
        "player_names",
        "start_period",
        "end_period",
    }
    assert all(item["collection_name"] == "knicks_test" for item in indexed)
