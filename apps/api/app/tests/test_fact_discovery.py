"""Discovery must answer casual prompts without giving generation control of facts."""

import pytest
from app.core.db import AsyncSessionLocal
from app.tests.support.player_archive import _seed_release_stats


@pytest.mark.parametrize(
    "question",
    [
        "Something surprising about Brunson in the playoffs?",
        "Something surprising about Brunson on 2026-01-02?",
        "Something surprising about Brunson in 2024-25?",
        "Something surprising about Nobody McFake?",
        "An interesting stat about the Lakers season",
    ],
)
async def test_missing_evidence_never_broadens_scope(client, monkeypatch, question):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", False)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert not body["citations"]
    assert "put up" not in body["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "Is Brunson injured today?",
        "Give me an interesting stat from the current season",
        "Something surprising about Brunson tonight?",
    ],
)
async def test_live_requests_are_not_reinterpreted_as_discovery(client, question):
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    assert response.json()["refused"]
    assert response.json()["citations"] == []


async def test_public_route_and_followup(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", False)
    async with AsyncSessionLocal() as db:
        release, player = await _seed_release_stats(db)
        version, player_id = release.version, player.id
    response = await client.post(
        "/analysis/query", json={"question": "Something surprising about Brunson?"}
    )
    assert response.status_code == 200
    first = response.json()
    assert first["route"] == "discover_fact" and not first["refused"]
    assert "Jalen Brunson put up 30 points" in first["answer"]
    receipt = first["citations"][0]
    assert receipt["claim"] in first["answer"]
    assert receipt["metadata"]["data_version"] == version
    assert receipt["game_id"] in receipt["metadata"]["source_game_ids"]
    assert receipt["metadata"]["player_ids"] == [player_id]
    response = await client.post(
        "/analysis/query",
        json={"question": "Give me another one", "conversation_state": first["conversation_state"]},
    )
    assert response.status_code == 200
    second = response.json()
    assert "Jalen Brunson" in second["answer"] and "20 points" in second["answer"]
    assert second["citations"][0]["game_id"] != receipt["game_id"]
    assert second["citations"][0]["metadata"]["fact_id"] != receipt["metadata"]["fact_id"]
    response = await client.post(
        "/analysis/query",
        json={"question": "One more", "conversation_state": second["conversation_state"]},
    )
    assert response.status_code == 200
    assert not response.json()["citations"]
    assert "another verified fact" in response.json()["answer"]
    response = await client.post(
        "/analysis/query",
        json={
            "question": "Something surprising about Towns?",
            "conversation_state": first["conversation_state"],
        },
    )
    assert response.status_code == 200
    assert "Karl-Anthony Towns" in response.json()["answer"]


async def test_text_history_can_continue_discovery_without_repeating(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", False)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    question = "Something surprising about Brunson?"
    first = await client.post("/analysis/query", json={"question": question})
    assert first.status_code == 200
    response = await client.post(
        "/analysis/query",
        json={
            "question": "Another one",
            "context": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": first.json()["answer"]},
            ],
        },
    )
    assert response.status_code == 200
    assert "Jalen Brunson" in response.json()["answer"]
    assert "20 points" in response.json()["answer"]
