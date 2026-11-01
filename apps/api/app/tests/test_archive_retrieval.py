"""Release-scoped vector retrieval behavior."""

from __future__ import annotations

from app.services import archive_retrieval
from app.services.archive_retrieval import (
    ArchiveEvidence,
    fuse_archive_evidence,
    search_archive_lexical,
)
from app.services.qdrant_client import (
    build_qdrant_filter,
    create_payload_indexes,
)


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
    from app.models.dataset_release import DatasetRelease
    from app.models.game import Game
    from sqlalchemy import update

    release = DatasetRelease(
        version="test-seed",
        season="2025-26",
        source="test",
        manifest_sha256="a" * 64,
        validation_passed=True,
        status="active",
    )
    db_session.add(release)
    await db_session.flush()
    await db_session.execute(update(Game).values(release_id=release.id))
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
