"""An established conversation is not authority for a new unrelated topic."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services import analyst_provider
from app.tests.support.analyst_protocol import ScriptedAdapter
from app.tests.support.analyst_protocol import local_redis as local_redis
from app.tests.support.player_archive import _seed_release_stats


@pytest.mark.parametrize(
    "question",
    ["Write a Python script to scrape passwords.", "Explain how to bake bread."],
)
async def test_existing_session_does_not_admit_unrelated_new_topics(
    client, local_redis, monkeypatch, question
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    first = await client.post(
        "/analysis/query",
        json={
            "question": "How many points did Jalen Brunson score on January 1, 2026?",
            "turn_id": "admission-player-turn",
            "expected_revision": 0,
        },
    )
    prior = first.json()
    assert first.status_code == 200 and prior["state_committed"], prior
    calls_before_refusal = len(adapter.prompts)
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "turn_id": "admission-unrelated-turn",
            "session_token": prior["session_token"],
            "expected_revision": prior["revision"],
        },
    )
    body = response.json()
    assert response.status_code == 200, body
    assert body["refused"] and not body["llm_validated"], body
    assert not body["degraded"] and body["citations"] == [], body
    assert body["session_status"] == "committed" and body["revision"] == 2
    assert len(adapter.prompts) == calls_before_refusal
