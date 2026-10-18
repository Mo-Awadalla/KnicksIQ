"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

from app.api import analysis
from app.api import analysis_policy as runtime
from app.api import analysis_retrieval as retrieval
from app.tests.analysis_test_support import (
    isolate_response_cache as isolate_response_cache,
)


async def test_redis_failure_marks_factual_answer_degraded(client, monkeypatch):
    async def redis_degraded(_request):
        return True

    monkeypatch.setattr(analysis, "_rate_limit", redis_degraded)

    response = await client.post(
        "/analysis/query",
        json={"question": "What is the Knicks record this season?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["degraded"] is True
    assert body["citations"]
    assert "NYK is" in body["answer"]


async def test_degraded_cache_entry_is_ignored(client, monkeypatch):
    async def stale_cache(_key):
        return {"answer": "stale degraded answer", "degraded": True}

    monkeypatch.setattr(analysis, "get_cached_answer", stale_cache)

    response = await client.post(
        "/analysis/query",
        json={"question": "What is the Knicks record this season?"},
    )

    assert response.status_code == 200
    assert "stale degraded answer" not in response.json()["answer"]
    assert "NYK is" in response.json()["answer"]


async def test_shadow_mode_returns_deterministic_answer_and_runs_candidate_in_background(
    client,
    monkeypatch,
):
    original_settings = runtime.get_settings()
    captured = []

    class ShadowSettings:
        analysis_answer_mode = "shadow"
        analysis_shadow_sample_rate = 1.0
        test_mode = False
        public_chat_max_prompt_chars = 1200
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def healthy_rate_limit(_request):
        return False

    async def shadow_candidate(**kwargs):
        captured.append(kwargs)

    cache = {}

    async def get_cached(key):
        return cache.get(key)

    async def set_cached(key, value):
        cache[key] = value

    monkeypatch.setattr(runtime, "get_settings", lambda: ShadowSettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "get_cached_answer", get_cached)
    monkeypatch.setattr(analysis, "set_cached_answer", set_cached)
    monkeypatch.setattr(retrieval, "_run_shadow_candidate", shadow_candidate)

    response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )
    cached_response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )

    assert response.status_code == 200
    assert cached_response.status_code == 200
    body = response.json()
    assert "score-margin range" in body["answer"]
    assert {call["tool"] for call in body["tool_calls"]} == {"table_rag"}
    assert len(captured) == 2
    assert "score-margin range" in captured[0]["evidence"]["fact:table"]
    assert "score-margin range" in captured[1]["evidence"]["fact:cached"]
