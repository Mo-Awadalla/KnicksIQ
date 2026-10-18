"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.models.game import Game
from app.tests.analysis_test_support import (
    isolate_response_cache as isolate_response_cache,
)


async def test_public_analysis_valid_question_recovers_after_off_topic_context(client):
    context = [
        {
            "role": "user",
            "content": "who are you",
        },
        {
            "role": "assistant",
            "content": (
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games."
            ),
        },
        {
            "role": "user",
            "content": "can the knicks solve two sum in leetcode",
        },
        {
            "role": "assistant",
            "content": (
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games."
            ),
        },
        {
            "role": "user",
            "content": "nice",
        },
        {
            "role": "assistant",
            "content": (
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games."
            ),
        },
    ]

    r = await client.post(
        "/analysis/query",
        json={
            "question": "who beat the knicks by the most points",
            "context": context[-4:],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert "biggest 2025-26 Knicks loss in the available data" in body["answer"]
    assert body["tool_calls"]


async def test_public_analysis_accepts_natural_archive_phrasings(client):
    questions = [
        "What happened in the 4th quarter?",
        "Why did the Knicks lose?",
        "Who led the Knicks in scoring?",
        "Show me games where Towns dominated.",
        "Tell me about Mikal Bridges defense.",
        "Give me receipts for Brunson clutch moments.",
        "What went wrong against Boston?",
        "Did the Knicks shoot well from three?",
        "What do you know about a game that is not in the data?",
    ]

    for question in questions:
        r = await client.post("/analysis/query", json={"question": question})
        assert r.status_code == 200
        body = r.json()
        assert body["refused"] is False, question
        assert "Short answer" in body["answer"], question
        assert "cached" not in body["answer"].lower(), question


async def test_suggested_wildest_swings_question_returns_ranked_games(client):
    response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert "score-margin range" in body["answer"]
    assert "1." in body["answer"]
    assert body["citations"]
    assert body["warnings"] == []


async def test_opponent_performance_prompt_uses_only_matching_games(client):
    games = (await client.get("/games")).json()
    matching = [g for g in games if "TOR" in {g["home_team_id"], g["away_team_id"]}]
    assert matching and len(matching) < len(games)
    wins = sum(g["winner_team_id"] == "NYK" for g in matching)
    response = await client.post(
        "/analysis/query", json={"question": "How did they perform against Toronto?"}
    )
    body = response.json()
    assert response.status_code == 200
    assert f"{wins}-{len(matching) - wins}" in body["answer"]
    assert "not have enough" not in body["answer"]
    cited_games = {citation["game_id"] for citation in body["citations"] if citation["game_id"]}
    assert cited_games == {game["id"] for game in matching}


async def test_back_to_back_count_requests_definition_instead_of_points(client):
    response = await client.post(
        "/analysis/query",
        json={"question": "How many back-to-backs did they win in February?"},
    )
    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "second game" in answer
    assert "both games" in answer
    assert "total points" not in answer


@pytest.mark.parametrize("question", ["How did NYK do vs TOR?", "How did they do v TOR?"])
async def test_team_matchup_alias_question_returns_full_record(client, question):
    games = (await client.get("/games?team_id=TOR")).json()
    wins = sum(game["winner_team_id"] == "NYK" for game in games)
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    assert response.json()["route"] == "table_rag"
    assert f"{wins}-{len(games) - wins}" in response.json()["answer"]


async def test_ambiguous_narrative_requests_game_selection_without_receipts(client):
    response = await client.post(
        "/analysis/query", json={"question": "What happened in the fourth quarter?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "clarification"
    assert "Which game" in body["answer"]
    assert body["refused"] is False
    assert body["citations"] == []


async def test_follow_up_requires_verified_game_and_event_reference(client):
    response = await client.post(
        "/analysis/query",
        json={
            "question": "What did Brunson do during it?",
            "context": [
                {"role": "user", "content": "Tell me about the Knicks season."},
                {"role": "assistant", "content": "A decisive scoring run changed everything."},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["route"] == "clarification"
    assert response.json()["citations"] == []


async def test_specific_final_minutes_return_only_matching_event_receipts(client):
    game = (await client.get("/games/1")).json()
    response = await client.post(
        "/analysis/query",
        json={"question": f"What happened in the final two minutes on {game['game_date']}?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "retrieval_rag"
    assert body["evidence"]
    for item in body["evidence"]:
        assert item["game_id"] == game["id"]
        for row in item["rows"]:
            assert row["period"] == 4
            minutes, seconds = map(int, row["clock"].split(":"))
            assert minutes * 60 + seconds <= 120
    assert all(citation["type"] != "document" for citation in body["citations"])


async def test_best_defensive_game_binds_lowest_points_allowed_before_retrieval(client):
    games = (await client.get("/games")).json()

    def allowed(game):
        return game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]

    best = min(games, key=allowed)
    response = await client.post(
        "/analysis/query", json={"question": "Explain the Knicks' best defensive game."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "retrieval_rag"
    assert "fewest points allowed" in body["answer"]
    assert "do not establish why the defense succeeded" in body["answer"]
    assert str(allowed(best)) in body["answer"]
    assert best["game_date"] in body["answer"]
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {best["id"]}
    assert all(item["game_id"] == best["id"] for item in body["evidence"])


@pytest.mark.parametrize(
    "question",
    [
        "How did the Knicks erase their largest deficit?",
        "What was the most damaging opponent run this season?",
        "What was the Knics biggest run?",
        "What was NY's worst collpase?",
    ],
)
async def test_season_run_superlative_preserves_scope_and_requests_metric(client, question):
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "clarification"
    assert "season-wide ranking" in body["answer"]
    assert "time window" in body["answer"]
    assert "Which game" not in body["answer"]
    assert body["citations"] == []


async def test_narrative_game_choices_disclose_truncated_dates(client, db_session):
    for offset in range(9):
        db_session.add(
            Game(
                nba_game_id=f"clarify-atl-{offset}",
                season="2025-26",
                game_date=date(2026, 3, 1) + timedelta(days=offset),
                home_team_id="NYK",
                away_team_id="ATL",
                home_score=110,
                away_score=100,
                status="final",
                season_type="regular",
            )
        )
    await db_session.commit()
    response = await client.post(
        "/analysis/query", json={"question": "Explain the Knicks game against Atlanta."}
    )
    body = response.json()
    assert body["route"] == "clarification"
    assert "Showing the first 8:" in body["answer"]
    assert "2026-03-01" in body["answer"]
    assert "2026-03-09" not in body["answer"]
