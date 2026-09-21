"""Discovery must answer casual prompts without giving generation control of facts."""

import pytest
from app.core.db import AsyncSessionLocal
from app.services import fact_discovery
from app.services.fact_discovery import discover_fact
from app.tests.test_player_intelligence import _seed_release_stats


@pytest.mark.parametrize(
    "question",
    [
        "Give me an interesting stat from the season",
        "Something surprising about Brunson?",
        "Tell me a fun fact",
    ],
)
async def test_discovery_has_exact_claim_and_receipt(db_session, question):
    release, player = await _seed_release_stats(db_session)
    answer = await discover_fact(
        db_session, question=question, season="2025-26", prior=None, context=[]
    )
    assert answer.route == "discover_fact"
    assert "2025-26 archive" in answer.answer
    assert answer.citations
    receipt = answer.citations[0]
    assert receipt["claim"] in answer.answer
    assert receipt["metadata"]["data_version"] == release.version
    assert receipt["game_id"] in receipt["metadata"]["source_game_ids"]
    if "Brunson" in question:
        assert "Jalen Brunson put up 30 points" in answer.answer
        assert receipt["metadata"]["player_ids"] == [player.id]
    assert "season-high" not in answer.answer
    assert "Short answer" not in answer.answer


async def test_another_preserves_player_scope_and_exhausts_without_repetition(db_session):
    await _seed_release_stats(db_session)
    first = await discover_fact(
        db_session,
        question="Something surprising about Brunson?",
        season="2025-26",
        prior=None,
        context=[],
    )
    second = await discover_fact(
        db_session, question="Give me another one", season="2025-26", prior=first.state, context=[]
    )
    assert "Jalen Brunson" in second.answer
    assert first.citations[0]["game_id"] != second.citations[0]["game_id"]
    assert "20 points" in second.answer
    third = await discover_fact(
        db_session, question="One more", season="2025-26", prior=second.state, context=[]
    )
    assert not third.citations
    assert "another verified fact" in third.answer


async def test_text_history_followup_and_explicit_player_change(db_session):
    await _seed_release_stats(db_session)
    question = "Something surprising about Brunson?"
    first = await discover_fact(
        db_session, question=question, season="2025-26", prior=None, context=[]
    )
    second = await discover_fact(
        db_session,
        question="Another one",
        season="2025-26",
        prior=None,
        context=[
            {"role": "user", "content": question},
            {"role": "assistant", "content": first.answer},
        ],
    )
    assert "Jalen Brunson" in second.answer and "20 points" in second.answer
    change = await discover_fact(
        db_session,
        question="Something surprising about Towns?",
        season="2025-26",
        prior=first.state,
        context=[],
    )
    assert "Karl-Anthony Towns" in change.answer


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
async def test_missing_evidence_never_broadens_scope(db_session, question):
    await _seed_release_stats(db_session)
    answer = await discover_fact(
        db_session, question=question, season="2025-26", prior=None, context=[]
    )
    assert not answer.citations
    assert "put up" not in answer.answer


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


async def test_public_route_and_followup(client):
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = await client.post(
        "/analysis/query", json={"question": "Give me an interesting stat"}
    )
    first = response.json()
    assert response.status_code == 200
    assert first["route"] == "discover_fact" and not first["refused"]
    assert first["citations"]
    second = (
        await client.post(
            "/analysis/query",
            json={
                "question": "Give me another one",
                "conversation_state": first["conversation_state"],
            },
        )
    ).json()
    assert (
        second["citations"][0]["metadata"]["fact_id"]
        != first["citations"][0]["metadata"]["fact_id"]
    )


async def test_legacy_rollback_uses_deterministic_selection():
    choice = await fact_discovery._choose(
        [{"fact_id": "verified", "statement": "A verified claim."}], "Interesting stat?", False
    )
    assert choice.fact_id == "verified" and choice.opening == "here"
