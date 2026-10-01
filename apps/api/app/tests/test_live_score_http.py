"""Live-only HTTP regression with real SQL and local Redis.

Failure matrix specified before implementation: archival season totals answer a
live-only question; a model call invents a current score; a refusal is scored as
an archive answer; replay changes the refusal or consumes another model call;
session state is lost. A mixed archive/current question must remain eligible for
an archival answer and a live-data limitation.
"""

import json

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401, F811
from app.tests.test_player_intelligence import _seed_release_stats


@pytest.mark.parametrize("mode", ["disabled", "llm_primary", "shadow"])
async def test_live_score_refuses_without_model_or_archive_claims(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    mode,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", 1.0)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)

    def forbidden():
        raise AssertionError("A live-only refusal must not call a model")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", forbidden)
    payload = {
        "question": "What is the live score tonight?",
        "season": "2025-26",
        "turn_id": f"live-score-{mode}",
        "expected_revision": 0,
    }
    response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refused"] is True
    assert body["route"] is None
    assert body["state_committed"] is True
    assert body["citations"] == []
    assert "live" in body["answer"].lower()
    assert "injur" not in body["answer"].lower()
    assert "336" not in body["answer"]
    assert "3 over 3" not in body["answer"]
    replay = await client.post("/analysis/query", json=payload)
    assert replay.json() == body
    artifact = tmp_path / f"live-score-{mode}.json"
    artifact.write_text(json.dumps({"input": payload, "response": body}, indent=2))
    record_property("live_score_artifact", str(artifact))


async def test_mixed_archive_and_live_score_keeps_archived_answer(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = await client.post(
        "/analysis/query",
        json={
            "question": (
                "What was the score against Boston on January 3, 2026, "
                "and what is the live score tonight?"
            ),
            "season": "2025-26",
            "turn_id": "mixed-score-turn-1",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refused"] is False
    assert body["route"] == "factual_fallback"
    assert "113" in body["answer"] and "100" in body["answer"]
    assert "live" in body["answer"].lower()
    assert "injur" not in body["answer"].lower()
    assert body["citations"] and body["state_committed"]
