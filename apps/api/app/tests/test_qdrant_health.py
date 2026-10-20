"""Qdrant readiness probe: an unfinished probe is not a failed probe."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.api import health
from app.services import qdrant_client
from app.services.rag import search_possession_chunks


@pytest.fixture
def probe(monkeypatch):
    """Route the real probe machinery through a controllable inspector."""
    release = threading.Event()
    state: dict[str, object] = {"mode": "ok"}

    def inspect(_client=None):
        if state["mode"] == "slow":
            release.wait(5)
            return {"usable": True}
        if state["mode"] == "fail":
            raise RuntimeError("qdrant unreachable")
        if state["mode"] == "unusable":
            return {"usable": False}
        return {"usable": True}

    settings = SimpleNamespace(rag_qdrant_enabled=True)
    monkeypatch.setattr(qdrant_client, "get_settings", lambda: settings)
    monkeypatch.setattr(qdrant_client, "inspect_retrieval_targets", inspect)
    monkeypatch.setattr(qdrant_client, "_health_future", None)
    monkeypatch.setattr(qdrant_client, "_health_checked_at", 0.0)
    monkeypatch.setattr(qdrant_client, "_health_result", False)
    yield state
    release.set()
    future = qdrant_client._health_future
    if future is not None:
        future.result(timeout=5)


async def _ready_qdrant(client, monkeypatch) -> str:
    settings = SimpleNamespace(
        require_active_release=False,
        test_mode=True,
        is_production=False,
        rag_qdrant_enabled=True,
        redis_url=None,
        ai_provider="mock",
        openrouter_api_key=None,
        ai_api_key=None,
    )
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    return response.json()["optional_dependencies"]["qdrant"]


async def test_slow_first_probe_reports_checking_not_degraded(client, monkeypatch, probe):
    probe["mode"] = "slow"
    assert await _ready_qdrant(client, monkeypatch) == "checking"
    rag = (await client.get("/health/rag")).json()
    assert rag["status"] == "checking"


async def test_completed_ok_probe_reports_ok(client, monkeypatch, probe):
    probe["mode"] = "ok"
    assert await _ready_qdrant(client, monkeypatch) == "ok"


@pytest.mark.parametrize("mode", ["fail", "unusable"])
async def test_failed_probe_reports_degraded(client, monkeypatch, probe, mode):
    probe["mode"] = mode
    assert await _ready_qdrant(client, monkeypatch) == "degraded"


def _rag_settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.rag.get_settings",
        lambda: SimpleNamespace(
            rag_hybrid_enabled=True,
            rag_qdrant_enabled=True,
            rag_reranker_enabled=False,
            rag_rerank_limit=20,
        ),
    )
    attempts: list[str] = []

    def record_embed(texts):
        attempts.append(texts[0])
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr("app.services.rag.embed_texts", record_embed)
    return attempts


async def test_rag_attempts_search_while_first_probe_runs(monkeypatch, db_session, probe):
    probe["mode"] = "slow"
    attempts = _rag_settings(monkeypatch)
    chunks, _ = await search_possession_chunks(
        db_session, "What happened in the Knicks game against Toronto?", season="2025-26"
    )
    assert attempts
    assert chunks


async def test_rag_skips_search_after_failed_probe(monkeypatch, db_session, probe):
    probe["mode"] = "fail"
    attempts = _rag_settings(monkeypatch)
    chunks, _ = await search_possession_chunks(
        db_session, "What happened in the Knicks game against Toronto?", season="2025-26"
    )
    assert attempts == []
    assert chunks
