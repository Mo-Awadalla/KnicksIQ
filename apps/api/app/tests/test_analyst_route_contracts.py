"""Public analyst route commits, replays, stateless fallback and conversation contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from app.core.config import get_settings
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services import analyst_provider, analyst_sessions
from app.tests.support.analyst_protocol import (
    ScriptedAdapter,
)
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)
from app.tests.support.analytics_workflows import seed_operations_archive
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import select


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mode", ["deterministic", "shadow"])
async def test_narrative_uses_active_release_in_each_profile(client, monkeypatch, enabled, mode):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", enabled)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", 0.0)
    async with AsyncSessionLocal() as db:
        release = await seed_operations_archive(db)
        version = release.version
        active_game_id = (
            await db.execute(
                select(Game.id).where(
                    Game.release_id == release.id, Game.game_date == date(2026, 1, 21)
                )
            )
        ).scalar_one()
        staged = DatasetRelease(
            version="narrative-staged-test",
            season="2025-26",
            source="test",
            manifest_sha256="b" * 64,
            validation_passed=True,
            status="staged",
        )
        db.add(staged)
        await db.flush()
        db.add(
            Game(
                release_id=staged.id,
                nba_game_id="staged-narrative",
                season="2025-26",
                game_date=date(2026, 1, 21),
                home_team_id="NYK",
                away_team_id="BKN",
                home_score=199,
                away_score=50,
                status="final",
                season_type="regular",
            )
        )
        await db.commit()

    response = await client.post(
        "/analysis/query", json={"question": "What happened in the Knicks game on 2026-01-21?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data_version"] == version
    assert body["refused"] is False
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {active_game_id}
    assert "199" not in body["answer"]
    assert "120" in body["answer"] and "66" in body["answer"]
    assert "BKN" in body["answer"]
    assert "2026-01-21" in body["answer"]


async def test_route_commits_replays_and_ignores_client_authority(client, local_redis, monkeypatch):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    request = {
        "question": "Give me an interesting stat",
        "turn_id": "integration-turn-0001",
        "expected_revision": 0,
        "conversation_state": {"player_ids": [999]},
    }
    first = await client.post("/analysis/query", json=request)
    assert first.status_code == 200
    response = first.json()
    assert response["state_committed"] and response["revision"] == 1
    assert response["session_status"] == "committed"
    assert response["llm_validated"]
    replay = await client.post("/analysis/query", json=request)
    assert replay.json() == response
    assert len(adapter.prompts) == 3
    conflict = await client.post("/analysis/query", json={**request, "question": "Different input"})
    assert conflict.status_code == 409
    for question in ("Are the Knicks playing live tonight?", "Show possessions not in the data."):
        conflict = await client.post("/analysis/query", json={**request, "question": question})
        assert conflict.status_code == 409
    second = await client.post(
        "/analysis/query",
        json={
            "question": "Why is that interesting?",
            "turn_id": "integration-turn-0002",
            "session_token": response["session_token"],
            "expected_revision": 1,
        },
    )
    assert second.json()["llm_validated"] and second.json()["revision"] == 2
    assert len(adapter.prompts) == 5


async def test_redis_failure_gives_explicit_stateless_facts(client, monkeypatch):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)

    async def unavailable():
        return None

    monkeypatch.setattr(analyst_sessions, "_redis", unavailable)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = (
        await client.post(
            "/analysis/query", json={"question": "Brunson points", "turn_id": "stateless-turn-0001"}
        )
    ).json()
    assert not response["state_committed"] and response["session_token"] is None
    assert not response["llm_validated"] and response["citations"]
    assert response["session_status"] == "unavailable"


async def test_six_turn_conversation_protocol(client, local_redis, monkeypatch):
    """State/evidence protocol only; actual-provider acceptance is a separate blocked gate."""
    from app.core.db import AsyncSessionLocal
    from app.models.game import Game
    from sqlalchemy import select

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(get_settings(), "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            await db.execute(
                select(Game)
                .where(Game.release_id == release.id)
                .order_by(Game.game_date.desc())
                .limit(1)
            )
        ).scalar_one()
        game.season_type = "playoffs"
        await db.commit()

    class ConversationAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            raw = await super().generate(system=system, user=user)
            payload, value = json.loads(user), json.loads(raw)
            if payload["schema"]["title"] == "Action" and value.get("answer"):
                question = payload["question"]
                if "prove" in question:
                    value["answer"]["text"] += (
                        " A single observation does not prove overall improvement."
                    )
                if "injured" in question:
                    value["answer"]["text"] += " I don't have live injury updates."
            return json.dumps(value)

    adapter = ConversationAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    questions = [
        "Give me an interesting stat.",
        "Why is that interesting?",
        "Another one, but about a different player.",
        "Now only playoff games.",
        "Does that prove he was playing better?",
        "Is he injured today, and how did he perform in the archived playoffs?",
    ]
    response, outputs = {}, []
    for index, question in enumerate(questions):
        request = {
            "question": question,
            "turn_id": f"six-turn-protocol-{index:03}",
            "session_token": response.get("session_token"),
            "expected_revision": response.get("revision", 0),
        }
        http = await client.post("/analysis/query", json=request)
        assert http.status_code == 200, http.text
        response = http.json()
        assert response["llm_validated"], response
        assert response["state_committed"] and response["revision"] == index + 1
        outputs.append(response)
    first = outputs[0]["citations"][0]["metadata"]["claim"]
    different = outputs[2]["citations"][0]["metadata"]["claim"]
    assert first["subject_id"] != different["subject_id"]
    assert outputs[3]["citations"][0]["metadata"]["claim"]["season_type"] == "playoffs"
    assert "does not prove" in outputs[4]["answer"]
    assert "don't have live injury" in outputs[5]["answer"]
    assert outputs[5]["citations"]


async def test_commit_deadline_preserves_release_authority_for_retry(
    client, local_redis, monkeypatch
):
    import asyncio

    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    monkeypatch.setattr(settings, "analyst_deadline_seconds", 0.1)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)

    async def stalled_commit(*args):
        await asyncio.sleep(10)
        return False

    monkeypatch.setattr(analyst_sessions.SessionTurn, "commit", stalled_commit)
    response = await client.post(
        "/analysis/query",
        json={
            "question": "How many points did Jalen Brunson average?",
            "turn_id": "deadline-release-authority",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_status"] == "retryable"
    assert body["data_version"] == "analytics-test"
    assert body["state_committed"] is False
    assert body["revision"] is None


@pytest.mark.parametrize(
    "question",
    [
        "Summarize the Boston game on January 1, 2026 and cite the game report.",
        "Summarize Jalen Brunson's game on January 1, 2026 and cite the game report.",
    ],
)
async def test_requested_report_is_retrieved_after_a_committed_player_answer(
    client, local_redis, monkeypatch, question
):
    from app.core.db import AsyncSessionLocal
    from app.models.report import Report

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            await db.execute(
                select(Game).where(
                    Game.release_id == release.id, Game.game_date == date(2026, 1, 1)
                )
            )
        ).scalar_one()
        db.add(
            Report(
                release_id=release.id,
                game_id=game.id,
                reviewed=True,
                title="Boston postgame report",
                summary="The Knicks beat Boston 111-100.",
            )
        )
        await db.commit()
        game_id = game.id

    class ReportAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            value = json.loads(await super().generate(system=system, user=user))
            if payload["schema"]["title"] == "AnswerReview":
                value["assertions"][0]["supporting_evidence_ids"] = payload["proposed_answer"][
                    "evidence_ids"
                ]
            elif payload["schema"]["title"] == "Action":
                reports = [
                    item for item in payload["evidence"] if item.get("source_type") == "game_report"
                ]
                if reports:
                    value = {
                        "action": "answer_from_available_evidence",
                        "tools": [],
                        "answer": {
                            "text": "The Knicks beat Boston 111-100.",
                            "claims": [],
                            "evidence_ids": [reports[0]["evidence_id"]],
                            "fact_ids": [],
                        },
                    }
            return json.dumps(value)

    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: ReportAdapter())
    first = await client.post(
        "/analysis/query",
        json={
            "question": "How many points did Jalen Brunson score on January 1, 2026?",
            "turn_id": "report-followup-player",
            "expected_revision": 0,
        },
    )
    prior = first.json()
    assert first.status_code == 200 and prior["state_committed"], prior
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "turn_id": "report-followup-summary",
            "session_token": prior["session_token"],
            "expected_revision": prior["revision"],
        },
    )
    body = response.json()
    assert response.status_code == 200 and body["llm_validated"], body
    assert "111-100" in body["answer"]
    assert any(
        item["game_id"] == game_id and item["metadata"].get("source_type") == "reports"
        for item in body["citations"]
    ), body
