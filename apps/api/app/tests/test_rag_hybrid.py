"""Tests for optional hybrid RAG helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from app.services import embeddings
from app.services.possession_chunks import PossessionChunk
from app.services.qdrant_client import ensure_collections, qdrant_point_id, upsert_points
from app.services.rag import reciprocal_rank_fusion, search_possession_chunks
from app.services.reranker import rerank_candidates


class _FakeEmbeddingModel:
    calls = 0

    def encode(self, texts, **_kwargs):
        self.calls += 1
        return [[float(index)] * 1024 for index, _text in enumerate(texts, start=1)]


def test_embed_texts_returns_empty_without_loading_model(monkeypatch):
    def fail_loader():
        raise AssertionError("model should not load for empty input")

    monkeypatch.setattr(embeddings, "_load_model", fail_loader)
    assert embeddings.embed_texts([]) == []


def test_embed_texts_shape_and_loader_cache(monkeypatch):
    fake = _FakeEmbeddingModel()
    loader_calls = {"count": 0}

    def fake_loader():
        loader_calls["count"] += 1
        return fake

    monkeypatch.setattr(embeddings, "_load_model", fake_loader)
    vectors = embeddings.embed_texts(["one", "two"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 1024
    assert loader_calls["count"] == 1


class _FakeModels:
    class Distance:
        COSINE = "Cosine"

    class VectorParams:
        def __init__(self, size, distance):
            self.size = size
            self.distance = distance

    class PointStruct:
        def __init__(self, id, vector, payload):
            self.id = id
            self.vector = vector
            self.payload = payload


class _FakeQdrantClient:
    def __init__(self):
        self.created = []
        self.upserts = []

    def get_collections(self):
        return SimpleNamespace(collections=[])

    def create_collection(self, collection_name, vectors_config):
        self.created.append((collection_name, vectors_config.size, vectors_config.distance))

    def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))


def test_qdrant_collections_and_upsert_payload_shape(monkeypatch):
    monkeypatch.setitem(sys.modules, "qdrant_client", SimpleNamespace(models=_FakeModels))
    client = _FakeQdrantClient()

    ensure_collections(client)
    assert ("knicks_possessions", 1024, "Cosine") in client.created

    count = upsert_points(
        "knicks_possessions",
        [
            {
                "id": "game:1:poss:0",
                "payload": {
                    "game_id": 1,
                    "date": "2025-10-22",
                    "opponent": "TOR",
                    "start_period": 1,
                    "end_period": 1,
                    "player_names": ["Jalen Brunson"],
                    "text": "Q1 possession",
                },
            }
        ],
        [[0.1] * 1024],
        client=client,
    )
    point = client.upserts[0][1][0]
    assert count == 1
    assert point.id == str(qdrant_point_id("game:1:poss:0"))
    assert point.payload["chunk_id"] == "game:1:poss:0"
    assert point.payload["player_names"] == ["Jalen Brunson"]


def test_rrf_ordering_is_deterministic_for_ties():
    fused = reciprocal_rank_fusion(
        [[("b", 10.0), ("a", 9.0)], [("a", 8.0), ("b", 7.0)]],
        limit=2,
    )
    assert fused == [
        ("a", pytest.approx(1 / 61 + 1 / 62)),
        ("b", pytest.approx(1 / 61 + 1 / 62)),
    ]


async def test_qdrant_failure_falls_back_to_lexical_retrieval(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.rag.get_settings",
        lambda: SimpleNamespace(
            rag_hybrid_enabled=True,
            rag_qdrant_enabled=True,
            rag_reranker_enabled=False,
            rag_rerank_limit=20,
        ),
    )
    monkeypatch.setattr("app.services.rag.is_qdrant_healthy", lambda: True)

    def fail_embed(_texts):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr("app.services.rag.embed_texts", fail_embed)
    trace: list[dict] = []
    chunks, filters = await search_possession_chunks(
        db_session,
        "What happened in the Knicks game against Toronto?",
        season="2025-26",
        trace=trace,
    )
    assert filters.as_dict()
    assert chunks
    assert any(call.get("tool") == "qdrant_search" for call in trace)
    assert any(call.get("tool") == "lexical_search" for call in trace)


def test_reranker_reorders_and_respects_top_n():
    candidates = [
        PossessionChunk("a", 1, "first", {}, []),
        PossessionChunk("b", 1, "second", {}, []),
        PossessionChunk("c", 1, "third", {}, []),
    ]
    model = SimpleNamespace(predict=lambda _pairs: [0.2, 0.9, 0.1])
    ranked = rerank_candidates("query", candidates, top_n=2, model=model)
    assert [item.chunk_id for item in ranked] == ["b", "a"]


def test_reranker_failure_falls_back_to_fused_order():
    candidates = [
        PossessionChunk("a", 1, "first", {}, []),
        PossessionChunk("b", 1, "second", {}, []),
    ]

    def fail(_pairs):
        raise RuntimeError("reranker unavailable")

    model = SimpleNamespace(predict=fail)
    assert rerank_candidates("query", candidates, top_n=1, model=model) == candidates[:1]
