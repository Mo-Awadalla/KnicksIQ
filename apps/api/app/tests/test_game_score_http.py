"""Regression for the free-browser dated-score failure, through SQL + HTTP + Redis.

Failure matrix (specified before implementation): explicit dates broaden to a
month; game score becomes aggregate totals; invalid/missing-year dates guess a
scope; absent games borrow other games; non-final scores become final results;
away games reverse team labels; response loses citations or committed replay.
"""

import json
from datetime import date

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from sqlalchemy import select


@pytest.mark.parametrize(
    ("question", "variant", "expected"),
    [
        ("What was the score against Boston on January 3, 2026?", "home", "score"),
        ("What was the final score on January 3rd, 2026?", "away", "score"),
        ("What was the score against Boston on 2026-01-03?", "home", "score"),
        ("What was the score against Boston on February 30, 2026?", "home", "clarify"),
        ("What was the score against Boston on January 3?", "home", "clarify"),
        ("What was the score against Boston on 2026-01-09?", "home", "absent"),
        ("What was the score against Boston on 2026-01-03?", "scheduled", "unfinished"),
        ("What was the score against Boston?", "home", "clarify"),
    ],
)
async def test_game_score_scope_and_replay(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    question,
    variant,
    expected,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")

    def forbidden():
        raise AssertionError("Disabled score answers must not call a model")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", forbidden)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            await db.execute(
                select(Game).where(
                    Game.release_id == release.id, Game.game_date == date(2026, 1, 3)
                )
            )
        ).scalar_one()
        game_id = game.id
        if variant == "away":
            game.home_team_id, game.away_team_id = "BOS", "NYK"
            game.home_score, game.away_score = 100, 113
        elif variant == "scheduled":
            game.status = "scheduled"
        await db.commit()
    payload = {
        "question": question,
        "season": "2025-26",
        "turn_id": "score-regression",
        "expected_revision": 0,
    }
    response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state_committed"]
    assert body["route"] == ("clarification" if expected == "clarify" else "factual_fallback")
    if expected == "score":
        assert "113" in body["answer"] and "100" in body["answer"]
        assert "2026-01-03" in body["answer"] and "BOS" in body["answer"]
        assert body["citations"]
        assert {c["game_id"] for c in body["citations"]} == {game_id}
        claims = [c["metadata"]["claim"] for c in body["citations"]]
        assert all(c["metric_id"] == "game_score" for c in claims)
        assert all(c["value"] == {"NYK": 113, "BOS": 100} for c in claims)
    else:
        assert not body["citations"]
        if expected == "clarify":
            assert "?" in body["answer"]
        elif expected == "absent":
            assert "No archived games match" in body["answer"]
        else:
            assert "final" in body["answer"].lower()
    replay = await client.post("/analysis/query", json=payload)
    assert replay.json() == body
    artifact = tmp_path / "game-score-http.json"
    artifact.write_text(
        json.dumps({"input": payload, "variant": variant, "response": body}, indent=2)
    )
    record_property("game_score_artifact", str(artifact))
