"""Deterministic non-answer admission through HTTP, SQL and dedicated real Redis.

Failure modes were written first in the private RC admission-failure-modes.md.
These synthetic inputs exercise product scope, not evaluation gold or quality.
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.game import Game
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats

CASES = [
    ("live-score", "What is the live score tonight?", "refuse"),
    ("now-score", "What is the score now?", "refuse"),
    ("prediction", "Will the Knicks win their next game?", "refuse"),
    ("injury", "Who is injured today?", "refuse"),
    ("trade", "What trade should the Knicks make tomorrow?", "refuse"),
    ("future-date", "Show possessions from 2099-01-01.", "refuse"),
    ("standings", "What are the current Eastern Conference standings?", "refuse"),
    ("yesterday", "Did the Knicks win yesterday?", "refuse"),
    ("next-season", "How will Brunson play next season?", "refuse"),
    ("lakers-game", "What happened in the Lakers game?", "clarify"),
    ("boston-game", "Which Boston game do you mean?", "clarify"),
    ("good-game", "Was that a good game?", "clarify"),
    ("score", "What was the score?", "clarify"),
    ("comparison", "Who was better?", "clarify"),
    ("defense", "Explain their defense.", "clarify"),
    ("betting", "What is the best betting line for tonight?", "refuse"),
]


@pytest.mark.parametrize(
    ("mode", "rate"), [("disabled", 0), ("llm_primary", 0), ("shadow", 0), ("shadow", 1)]
)
@pytest.mark.parametrize(("case_id", "question", "disposition"), CASES)
async def test_non_answer_admission_commits_and_replays_without_model_or_budget(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    mode,
    rate,
    case_id,
    question,
    disposition,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", rate)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        for day in (4, 5):
            db.add(
                Game(
                    release_id=release.id,
                    nba_game_id=f"admission-lal-{day}",
                    season="2025-26",
                    game_date=date(2026, 1, day),
                    home_team_id="NYK",
                    away_team_id="LAL",
                    home_score=110,
                    away_score=100,
                    status="final",
                    season_type="regular",
                    source_name="synthetic",
                )
            )
        await db.commit()
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, 0)
    attempted_calls = 0

    def forbidden_adapter():
        nonlocal attempted_calls
        attempted_calls += 1
        raise AssertionError("Deterministic admission must precede provider admission")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", forbidden_adapter)
    payload = {
        "question": question,
        "season": "2025-26",
        "turn_id": f"admission-{case_id}-{mode}-{rate}",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    replay = await client.post("/analysis/query", json=payload)
    conflict = await client.post(
        "/analysis/query", json={**payload, "question": "Changed question"}
    )
    budget_after = (await local_redis.get(key)).decode()
    artifact_dir = Path(os.environ.get("KNICKSIQ_ADMISSION_ARTIFACT_DIR", str(tmp_path)))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / f"{case_id}-{mode}-{rate}.json"
    with artifact.open("x") as evidence:
        json.dump(
            {
                "input": payload,
                "http_status": response.status_code,
                "response": body,
                "capture": capture,
                "attempted_model_calls": attempted_calls,
                "replay_status": replay.status_code,
                "replay": replay.json(),
                "conflict_status": conflict.status_code,
                "budget_after": budget_after,
            },
            evidence,
            indent=2,
        )
    record_property("admission_artifact", str(artifact))
    assert response.status_code == 200, response.text
    assert body["route"] == ("clarification" if disposition == "clarify" else None)
    assert body["refused"] is (disposition == "refuse")
    assert body["answer"] and body["citations"] == []
    assert body["llm_validated"] is False
    assert body["state_committed"] and body["session_token"] and body["revision"] == 1
    assert attempted_calls == 0 and capture["turn"]["model_calls"] == 0
    assert budget_after == "0"
    assert replay.status_code == 200 and replay.json() == body
    assert conflict.status_code == 409
    if case_id == "lakers-game":
        assert "2026-01-04" in body["answer"] and "2026-01-05" in body["answer"]
        assert "BOS" not in body["answer"]


async def test_committed_statistic_scopes_its_explanatory_followup(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    first = await client.post(
        "/analysis/query",
        json={
            "question": "What did Jalen Brunson average in his last 2 appearances?",
            "season": "2025-26",
            "turn_id": "admission-stat-first",
            "expected_revision": 0,
        },
    )
    original = first.json()
    payload = {
        "question": "Explain that average.",
        "season": "2025-26",
        "turn_id": "admission-stat-explain",
        "session_token": original["session_token"],
        "expected_revision": original["revision"],
    }
    response = await client.post("/analysis/query", json=payload)
    body = response.json()
    artifact_dir = Path(os.environ.get("KNICKSIQ_ADMISSION_ARTIFACT_DIR", str(tmp_path)))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / "committed-statistic-followup.json"
    with artifact.open("x") as evidence:
        json.dump(
            {"first": original, "followup_input": payload, "followup": body}, evidence, indent=2
        )
    record_property("admission_artifact", str(artifact))
    assert first.status_code == 200 and original["citations"]
    assert response.status_code == 200 and body["route"] == "factual_fallback"
    assert "25" in body["answer"] and body["citations"]
    assert body["state_committed"] and body["revision"] == 2
    assert (await client.post("/analysis/query", json=payload)).json() == body


@pytest.mark.parametrize(
    ("case_id", "question"),
    [
        (
            "lakers-mixed",
            "What was the Knicks record against the Lakers in 2025-26, and who is injured today?",
        ),
        ("delivered", "Explain how the Knicks delivered their biggest win on 2026-01-03."),
    ],
)
async def test_supported_archive_wording_and_opponents_are_not_refused(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    case_id,
    question,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        db.add(
            Game(
                release_id=release.id,
                nba_game_id="admission-lakers-mixed",
                season="2025-26",
                game_date=date(2026, 1, 4),
                home_team_id="NYK",
                away_team_id="LAL",
                home_score=110,
                away_score=100,
                status="final",
                season_type="regular",
                source_name="synthetic",
            )
        )
        await db.commit()
    payload = {
        "question": question,
        "season": "2025-26",
        "turn_id": f"wording-{case_id}",
        "expected_revision": 0,
    }
    response = await client.post("/analysis/query", json=payload)
    body = response.json()
    artifact_dir = Path(os.environ.get("KNICKSIQ_ADMISSION_ARTIFACT_DIR", str(tmp_path)))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / f"archive-wording-{case_id}.json"
    with artifact.open("x") as evidence:
        json.dump({"input": payload, "response": body}, evidence, indent=2)
    record_property("admission_artifact", str(artifact))
    assert response.status_code == 200 and body["refused"] is False
    assert body["route"] == "factual_fallback" and body["citations"]
    assert body["state_committed"] and body["revision"] == 1
    assert (await client.post("/analysis/query", json=payload)).json() == body
