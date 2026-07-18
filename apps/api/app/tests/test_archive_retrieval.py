"""Release-scoped vector retrieval behavior."""

from __future__ import annotations

from app.services import archive_retrieval
from app.services.archive_retrieval import (
    ArchiveEvidence,
    fuse_archive_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
from app.services.qdrant_client import (
    QdrantSearchResult,
    build_qdrant_filter,
    create_payload_indexes,
)


def test_archive_vector_search_injects_active_release_scope(monkeypatch):
    calls = []
    client = object()

    class Settings:
        rag_qdrant_enabled = True
        rag_qdrant_cloud_inference = True
        rag_qdrant_games_collection = "knicks_games"
        rag_qdrant_reports_collection = "knicks_reports"
        rag_qdrant_box_scores_collection = "knicks_box_scores"
        rag_qdrant_possessions_collection = "knicks_possessions"

    def search_batch(collection, queries, filters, top_k, *, client: object):
        calls.append((collection, queries, filters, top_k, client))
        return [
            [
                QdrantSearchResult(
                    id=f"{collection}:1",
                    score=0.9,
                    payload={"semantic_summary": f"{collection} Toronto archive fact"},
                )
            ]
        ]

    monkeypatch.setattr(archive_retrieval, "get_settings", lambda: Settings())
    monkeypatch.setattr(archive_retrieval, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(archive_retrieval, "search_collection_batch", search_batch)

    results = search_archive_vectors(
        queries=["Toronto turning points"],
        collections=["games", "reports"],
        filters={"team_ids": ["TOR"]},
        data_version="release-2025-26",
        limit=5,
        candidate_limit=20,
    )

    assert {call[0] for call in calls} == {"knicks_games", "knicks_reports"}
    assert all(call[1] == ["Toronto turning points"] for call in calls)
    assert all(call[2]["data_version"] == "release-2025-26" for call in calls)
    assert all(call[2]["team_ids"] == ["TOR"] for call in calls)
    assert all(call[3] == 20 for call in calls)
    assert all(call[4] is client for call in calls)
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


async def test_lexical_archive_search_is_independent_of_dense_results(db_session):
    trace: list[dict] = []

    results = await search_archive_lexical(
        db_session,
        query="TOR",
        collections=["games"],
        filters={"team_ids": ["TOR"]},
        data_version="test-seed",
        limit=30,
        trace=trace,
    )

    assert results
    assert all(item.collection == "games" for item in results)
    assert all(item.metadata["data_version"] == "test-seed" for item in results)
    assert all(item.metadata["retrieval_sources"] == ["lexical"] for item in results)
    assert trace[0]["retrieval_source"] == "lexical"


def test_fusion_deduplicates_and_traces_both_retrieval_sources(monkeypatch):
    monkeypatch.setattr(
        archive_retrieval,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"rag_lexical_weight": 1.25, "rag_dense_weight": 1.0, "rag_rrf_k": 60},
        )(),
    )
    shared_metadata = {"game_id": 2, "source_row_id": 2, "data_version": "v1"}
    lexical = [ArchiveEvidence("lexical:games:2", "games", "Toronto game", 1.0, shared_metadata)]
    dense = [ArchiveEvidence("vector:games:2", "games", "Toronto game", 0.9, shared_metadata)]

    results = fuse_archive_evidence(lexical, dense, limit=5)

    assert len(results) == 1
    assert results[0].metadata["retrieval_sources"] == ["dense", "lexical"]
