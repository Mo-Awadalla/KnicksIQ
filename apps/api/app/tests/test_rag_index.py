"""Tests for staged local RAG indexing."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services import qdrant_client, rag_index
from app.services.possession_chunks import PossessionChunk
from app.services.rag_index import build_rag_artifacts
from sqlalchemy import delete


async def _replace_games(db_session, count: int) -> list[Game]:
    await db_session.execute(delete(GameEvent))
    await db_session.execute(delete(Game))
    games = [
        Game(
            nba_game_id=f"staged-{index}",
            season="2025-26",
            game_date=date(2025, 10, 1) + timedelta(days=index),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=100 + index,
            away_score=90 + index,
            status="final",
            season_type="regular",
            data_status="events_ready",
        )
        for index in range(count)
    ]
    db_session.add_all(games)
    await db_session.commit()
    for game in games:
        await db_session.refresh(game)
    return games


async def test_build_rag_artifacts_limits_to_recent_games_and_reports_manifest(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    await _replace_games(db_session, 12)
    chunked_game_ids: list[int] = []
    reset_calls: list[str] = []
    upsert_calls: list[tuple[str, int]] = []

    def fake_chunks(game, _events, **_kwargs):
        chunked_game_ids.append(game.id)
        return [
            PossessionChunk(
                chunk_id=f"game:{game.id}:poss:0",
                game_id=game.id,
                text=f"{game.game_date} possession",
                metadata={
                    "game_id": game.id,
                    "date": str(game.game_date),
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "season": game.season,
                    "season_type": game.season_type,
                    "data_status": game.data_status,
                    "possession_index": 0,
                    "start_period": 1,
                    "end_period": 1,
                    "start_clock": "12:00",
                    "end_clock": "11:45",
                    "team_ids": ["NYK"],
                    "player_ids": [],
                    "player_names": [],
                    "row_count": 1,
                },
                rows=[{"description": "Knicks made shot"}],
            )
        ]

    monkeypatch.setattr("app.services.rag_index.build_possession_chunks", fake_chunks)
    monkeypatch.setattr(
        "app.services.rag_index.get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            rag_qdrant_enabled=True,
            rag_qdrant_possessions_collection="knicks_possessions",
        ),
    )
    monkeypatch.setattr(
        "app.services.rag_index.recreate_collection",
        lambda collection: reset_calls.append(collection),
    )
    monkeypatch.setattr(
        "app.services.rag_index.embed_texts",
        lambda texts: [[0.1] * 1024 for _text in texts],
    )

    def fake_upsert(collection, records, embeddings):
        upsert_calls.append((collection, len(records)))
        assert len(records) == len(embeddings)
        return len(records)

    monkeypatch.setattr("app.services.rag_index.upsert_points", fake_upsert)

    manifest = await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        game_limit=10,
        game_order="recent",
        reset_qdrant=True,
    )

    selected_dates = [item["date"] for item in manifest["selected_games"]]
    assert selected_dates == sorted(selected_dates, reverse=True)
    assert selected_dates[0] == "2025-10-12"
    assert selected_dates[-1] == "2025-10-03"
    assert len(chunked_game_ids) == 10
    assert manifest["available_games"] == 12
    assert manifest["selected_game_count"] == 10
    assert manifest["possession_chunk_count"] == 10
    assert manifest["qdrant_reset_requested"] is True
    assert manifest["qdrant_reset"] is True
    assert manifest["qdrant_upserted"] == 10
    assert reset_calls == ["knicks_possessions"]
    assert upsert_calls == [("knicks_possessions", 10)]


async def test_build_rag_artifacts_does_not_reset_qdrant_unless_requested(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    await _replace_games(db_session, 1)
    reset_calls: list[str] = []
    ensure_calls: list[bool] = []

    monkeypatch.setattr(
        "app.services.rag_index.build_possession_chunks",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.rag_index.get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            rag_qdrant_enabled=True,
            rag_qdrant_possessions_collection="knicks_possessions",
        ),
    )
    monkeypatch.setattr(
        "app.services.rag_index.recreate_collection",
        lambda collection: reset_calls.append(collection),
    )
    monkeypatch.setattr(
        "app.services.rag_index.ensure_collections",
        lambda: ensure_calls.append(True),
    )

    manifest = await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        reset_qdrant=False,
    )

    assert manifest["qdrant_reset_requested"] is False
    assert manifest["qdrant_reset"] is False
    assert reset_calls == []
    assert ensure_calls == []


class _CandidateStore:
    """Persistent resource state, including required server index metadata."""

    def __init__(self):
        self.collections = {}
        self.aliases = [
            SimpleNamespace(alias_name="retained_games", collection_name="retained_release")
        ]
        self.upsert_calls = 0
        self.fail_create = None

    def get_aliases(self):
        return SimpleNamespace(aliases=self.aliases)

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.collections]
        )

    def create_collection(self, collection_name, vectors_config):
        if collection_name in self.collections or collection_name == self.fail_create:
            raise RuntimeError("Collection create conflict")
        self.collections[collection_name] = {
            "vectors": vectors_config,
            "indexes": {},
            "points": {},
        }

    def create_payload_index(self, collection_name, field_name, field_schema, wait):
        self.collections[collection_name]["indexes"][field_name] = SimpleNamespace(
            data_type=field_schema
        )

    def get_collection(self, name):
        collection = self.collections[name]
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=collection["vectors"])),
            payload_schema=collection["indexes"],
        )

    def count(self, collection_name, exact, count_filter=None):
        points = list(self.collections[collection_name]["points"].values())
        if count_filter is not None:
            if count_filter.must:
                condition = count_filter.must[0]
                points = [
                    point
                    for point in points
                    if point.payload.get(condition.key) == condition.match.value
                ]
            if count_filter.must_not:
                condition = count_filter.must_not[0]
                points = [
                    point
                    for point in points
                    if point.payload.get(condition.key) != condition.match.value
                ]
        return SimpleNamespace(count=len(points))

    def upsert(self, collection_name, points):
        self.upsert_calls += 1
        stored = self.collections[collection_name]["points"]
        for point in points:
            stored[str(point.id)] = deepcopy(point)

    def scroll(self, collection_name, offset, limit, with_payload, with_vectors):
        points = list(self.collections[collection_name]["points"].values())
        start = offset or 0
        end = start + limit
        return points[start:end], end if end < len(points) else None


@pytest.fixture
def candidate_store(monkeypatch):
    settings = qdrant_client.get_settings().model_copy(
        update={
            "rag_qdrant_cloud_inference": False,
            "rag_qdrant_vector_size": 384,
            "rag_embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        }
    )
    store = _CandidateStore()
    monkeypatch.setattr(qdrant_client, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_index, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_index, "get_qdrant_client", lambda: store)
    monkeypatch.setattr(rag_index, "embed_texts", lambda texts: [[0.1] * 384 for _ in texts])
    return store, settings


def _candidate_sources(settings):
    return {
        alias: [
            {
                "id": source,
                "payload": {
                    "data_version": "test-candidate.1",
                    "game_id": 42,
                    "date": "2025-10-22",
                    "team_ids": ["NYK", "BOS"],
                    "semantic_summary": summary,
                },
            }
        ]
        for alias, source, summary in [
            (settings.rag_qdrant_possessions_collection, "game:42:poss:1", "Brunson made shot"),
            (settings.rag_qdrant_games_collection, "game:42:summary", "NYK 100 BOS 90"),
            (settings.rag_qdrant_box_scores_collection, "player-box:42:7", "Brunson 30 points"),
            (settings.rag_qdrant_reports_collection, "report:91", "Knicks win. Late surge."),
        ]
    }


def test_complete_candidate_is_reused_without_embeddings_or_resource_mutation(
    candidate_store, monkeypatch
):
    store, settings = candidate_store
    sources = _candidate_sources(settings)
    _counts, aliases, _reused = rag_index._prepare_release_collections(sources, "test-candidate.1")
    before = deepcopy(store.collections)
    original_aliases = deepcopy(store.aliases)
    original_upserts = store.upsert_calls

    def forbidden_embeddings(_texts):
        raise AssertionError("Reusing complete candidates must not call embeddings")

    monkeypatch.setattr(rag_index, "embed_texts", forbidden_embeddings)
    counts, reused_aliases, reused = rag_index._prepare_release_collections(
        _candidate_sources(settings), "test-candidate.1"
    )
    assert counts == {alias: 1 for alias in aliases}
    assert reused_aliases == aliases
    assert set(reused) == set(aliases.values())
    assert store.collections == before
    assert store.aliases == original_aliases
    assert store.upsert_calls == original_upserts


@pytest.mark.parametrize(
    "conflict",
    [
        "payload",
        "release",
        "source_id",
        "embedding_model",
        "embedding_mode",
        "embedding_document",
        "embedding_missing",
        "payload_index",
        "vector_dimension",
        "partial",
    ],
)
def test_later_candidate_conflict_prevents_every_write_and_embedding(
    candidate_store, monkeypatch, conflict
):
    store, settings = candidate_store
    _, aliases, _ = rag_index._prepare_release_collections(
        _candidate_sources(settings), "test-candidate.1"
    )
    # An absent first target must not be created before checking the final target.
    del store.collections[aliases[settings.rag_qdrant_possessions_collection]]
    reports = store.collections[aliases[settings.rag_qdrant_reports_collection]]
    point = next(iter(reports["points"].values()))
    if conflict == "payload":
        point.payload["semantic_summary"] = "Unapproved report"
    elif conflict == "release":
        point.payload["data_version"] = "other-release"
    elif conflict == "source_id":
        old_id = next(iter(reports["points"]))
        point.id = str(qdrant_client.qdrant_point_id("report:wrong"))
        reports["points"] = {str(point.id): reports["points"][old_id]}
    elif conflict == "embedding_model":
        point.payload["_index_embedding"]["model"] = "different-model"
    elif conflict == "embedding_mode":
        point.payload["_index_embedding"]["mode"] = "cloud"
    elif conflict == "embedding_document":
        point.payload["_index_embedding"]["document_sha256"] = "different-document"
    elif conflict == "embedding_missing":
        del point.payload["_index_embedding"]
    elif conflict == "payload_index":
        del reports["indexes"]["data_version"]
    elif conflict == "vector_dimension":
        point.vector = [0.1] * 383
    else:
        reports["points"].clear()
    before = deepcopy(store.collections)
    original_aliases = deepcopy(store.aliases)
    original_upserts = store.upsert_calls

    def forbidden_embeddings(_texts):
        raise AssertionError("Conflicting release must fail before embeddings")

    monkeypatch.setattr(rag_index, "embed_texts", forbidden_embeddings)
    with pytest.raises(RuntimeError):
        rag_index._prepare_release_collections(_candidate_sources(settings), "test-candidate.1")
    assert store.collections == before
    assert store.aliases == original_aliases
    assert store.upsert_calls == original_upserts


def test_serving_later_candidate_prevents_creation_of_missing_first_target(candidate_store):
    store, settings = candidate_store
    _, aliases, _ = rag_index._prepare_release_collections(
        _candidate_sources(settings), "test-candidate.1"
    )
    del store.collections[aliases[settings.rag_qdrant_possessions_collection]]
    store.aliases.append(
        SimpleNamespace(
            alias_name=settings.rag_qdrant_reports_collection,
            collection_name=aliases[settings.rag_qdrant_reports_collection],
        )
    )
    before = deepcopy(store.collections)
    with pytest.raises(RuntimeError, match="serving"):
        rag_index._prepare_release_collections(_candidate_sources(settings), "test-candidate.1")
    assert store.collections == before


def test_provider_create_conflict_never_overwrites_existing_target(candidate_store):
    store, settings = candidate_store
    sources = _candidate_sources(settings)
    name = qdrant_client.versioned_collection(
        settings.rag_qdrant_possessions_collection, "test-candidate.1"
    )
    store.fail_create = name
    with pytest.raises(RuntimeError, match="create conflict"):
        rag_index._prepare_release_collections(sources, "test-candidate.1")
    assert store.collections == {}
    assert store.upsert_calls == 0


async def test_versioned_reset_is_rejected_before_database_or_collection_access(
    db_session, monkeypatch, tmp_path
):
    def forbidden_query(*_args, **_kwargs):
        raise AssertionError("Versioned reset must fail before querying the source database")

    monkeypatch.setattr(db_session, "execute", forbidden_query)
    with pytest.raises(ValueError, match="create-only"):
        await build_rag_artifacts(
            db_session,
            season="2025-26",
            out_dir=tmp_path,
            data_version="test-candidate.1",
            reset_qdrant=True,
        )


def test_missing_candidate_is_created_without_rewriting_complete_siblings(
    candidate_store, monkeypatch
):
    store, settings = candidate_store
    _, aliases, _ = rag_index._prepare_release_collections(
        _candidate_sources(settings), "test-candidate.1"
    )
    possessions = aliases[settings.rag_qdrant_possessions_collection]
    del store.collections[possessions]
    complete_siblings = deepcopy(store.collections)
    original_aliases = deepcopy(store.aliases)
    original_upserts = store.upsert_calls
    embedding_calls = 0

    def embed_missing(texts):
        nonlocal embedding_calls
        embedding_calls += 1
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr(rag_index, "embed_texts", embed_missing)
    _, _, reused = rag_index._prepare_release_collections(
        _candidate_sources(settings), "test-candidate.1"
    )
    assert set(reused) == set(complete_siblings)
    assert {name: store.collections[name] for name in reused} == complete_siblings
    assert store.aliases == original_aliases
    assert store.upsert_calls == original_upserts + 1
    assert embedding_calls == 1
