"""Public analyst route commits, replays, stateless fallback and conversation contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services import analyst_loop, analyst_sessions
from app.tests.support.analyst_protocol import (
    ScriptedAdapter,
)
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)
from app.tests.support.player_archive import _seed_release_stats


async def test_route_commits_replays_and_ignores_client_authority(client, local_redis, monkeypatch):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
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
    assert response["llm_validated"]
    replay = await client.post("/analysis/query", json=request)
    assert replay.json() == response
    first_calls = len(adapter.prompts)
    assert first_calls <= 3
    conflict = await client.post("/analysis/query", json={**request, "question": "Different input"})
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
    # The second turn answers from committed claims: at most answer + review, and never
    # more than the original two-turn bound.
    assert first_calls < len(adapter.prompts) <= 5


async def test_redis_failure_gives_explicit_stateless_facts(client, monkeypatch):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)

    async def unavailable():
        return None

    monkeypatch.setattr(analyst_sessions, "_session_redis", unavailable)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = (
        await client.post(
            "/analysis/query", json={"question": "Brunson points", "turn_id": "stateless-turn-0001"}
        )
    ).json()
    assert not response["state_committed"] and response["session_token"] is None
    assert not response["llm_validated"] and response["citations"]
    assert any("Stateless" in warning for warning in response["warnings"])


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
            payload = json.loads(user)
            value = analyst_loop.decode_model_response(payload, json.loads(raw))
            if payload["schema"]["title"] in {"Action", "ProposedAnswer"}:
                answer = value.get("answer") if payload["schema"]["title"] == "Action" else value
                if answer:
                    question = payload["requested_question"]
                    if "prove" in question:
                        answer["text"] += (
                            " A single observation does not prove overall improvement."
                        )
                    if "injured" in question:
                        answer["text"] += " I don't have live injury updates."
            return json.dumps(analyst_loop.encode_model_response(payload, value))

    adapter = ConversationAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
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
