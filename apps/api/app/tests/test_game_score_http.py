"""Regression for the free-browser dated-score failure, through SQL + HTTP + Redis.

Failure matrix: explicit or release-calendar yearless dates broaden to a month;
game score becomes aggregate totals; invalid dates guess a scope; absent games
borrow other games; non-final scores become final results; away games reverse
team labels; response loses citations or committed replay identity.
"""

import json
from datetime import date

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
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
        ("What was the score against Boston on January 3?", "home", "score"),
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
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)

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
        source_metadata = {
            "date": str(game.game_date),
            "season_type": game.season_type,
            "home": game.home_team_id,
            "away": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
        }
        source_name, source_url = game.source_name, game.source_url
        await db.commit()
    payload = {
        "question": question,
        "season": "2025-26",
        "turn_id": "score-regression",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    with capture_turn() as replay_capture:
        replay = await client.post("/analysis/query", json=payload)
    artifact = tmp_path / "game-score-http.json"
    artifact.write_text(
        json.dumps(
            {
                "input": payload,
                "variant": variant,
                "canonical_game": {
                    "game_id": game_id,
                    "nba_game_id": game.nba_game_id,
                    "release": release.version,
                    "metadata": source_metadata,
                },
                "http_status": response.status_code,
                "response": body,
                "capture": capture,
                "replay_status": replay.status_code,
                "replay": replay.json(),
                "replay_capture": replay_capture,
            },
            indent=2,
        )
    )
    record_property("game_score_artifact", str(artifact))
    assert body["state_committed"]
    assert body["revision"] == 1
    assert body["session_token"]
    assert body["data_version"] == release.version
    assert not body["refused"]
    assert not body["llm_validated"]
    assert capture["turn"]["model_calls"] == 0
    assert body["route"] == ("clarification" if expected == "clarify" else "factual_fallback")
    scope = capture["turn"]["committed_evidence_proposal"]["scope"]
    results = [tool["result"] for tool in capture["tools"]]
    if expected == "score":
        assert scope["game_ids"] == [game_id]
        assert scope["date_start"] == scope["date_end"] == source_metadata["date"]
        assert not scope["requires_clarification"]
        assert body["citations"]
        assert {c["game_id"] for c in body["citations"]} == {game_id}
        issued_claims = {
            claim["claim_id"]: claim for result in results for claim in result["claims"]
        }
        issued_evidence = {
            evidence["evidence_id"]: evidence
            for result in results
            for evidence in result["evidence"]
        }
        for citation in body["citations"]:
            assert citation["type"] == "verified_claim"
            claim = citation["metadata"]["claim"]
            assert claim == issued_claims[claim["claim_id"]]
            assert claim["subject_id"] == "team:NYK"
            assert claim["metric_id"] == "game_score"
            assert claim["value"] == {"NYK": 113, "BOS": 100}
            assert claim["release_id"] == release.version
            assert claim["season"] == release.season
            assert claim["season_type"] == source_metadata["season_type"]
            assert claim["game_ids"] == [game_id]
            assert claim["sample_size"] == 1
            assert claim["denominator"] is None
            evidence_id = citation["metadata"]["evidence_id"]
            assert evidence_id in claim["supporting_evidence_ids"]
            evidence = issued_evidence[evidence_id]
            assert evidence["release_id"] == release.version
            assert evidence["game_id"] == game_id
            for key, value in source_metadata.items():
                assert evidence["metadata"][key] == value
            assert citation["source_name"] == evidence["source_name"] == source_name
            assert citation["source_url"] == evidence["source_url"] == source_url
    else:
        assert body["answer"]
        assert not body["citations"]
        assert all(not result["claims"] for result in results)
        if expected == "clarify":
            assert scope["requires_clarification"]
        elif expected == "absent":
            assert not scope["game_ids"]
            assert any(result["status"] == "no_matching_results" for result in results)
        else:
            assert scope["game_ids"] == [game_id]
            assert any(result["status"] == "unsupported_metric_or_scope" for result in results)
    assert replay.status_code == 200
    assert replay.json() == body
    assert replay_capture == {
        "searches": [],
        "tools": [],
        "turn": {"replayed": True, "model_calls": 0},
    }
