"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.models.game import Game
from app.tests.analysis_test_support import active_seed_release as active_seed_release
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


async def test_ambiguous_narrative_requests_game_selection_without_receipts(active_seed_release):
    client = active_seed_release
    response = await client.post(
        "/analysis/query", json={"question": "What happened in the fourth quarter?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert body["answer"]
    assert body["refused"] is False
    assert body["citations"] == []


@pytest.mark.parametrize(
    "question",
    [
        "How did the lineup with Brunson look in the Knicks game?",
        "What if the Knicks made two more threes in that game?",
    ],
)
async def test_unscoped_lineup_and_counterfactual_questions_request_a_game(
    active_seed_release, question
):
    response = await active_seed_release.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert not body["citations"]


async def test_season_summary_reports_the_active_archive_totals(active_seed_release):
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "What happened in the Knicks season?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    claims = {
        claim["metric_id"]: claim
        for citation in body["citations"]
        if (claim := citation["metadata"].get("claim"))
    }
    assert {
        metric: claims[metric]["value"] for metric in ("wins", "losses", "points", "margin")
    } == {
        "wins": 4,
        "losses": 1,
        "points": 564,
        "margin": 52,
    }
    assert all(claim["sample_size"] == 5 for claim in claims.values())
    assert all(set(claim["game_ids"]) == {1, 2, 3, 4, 5} for claim in claims.values())
    assert all(claim["release_id"] == "narrative-seed-test" for claim in claims.values())


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


async def test_specific_final_minutes_return_only_matching_event_receipts(active_seed_release):
    client = active_seed_release
    game = (await client.get("/games/1")).json()
    response = await client.post(
        "/analysis/query",
        json={"question": f"What happened in the final two minutes on {game['game_date']}?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    assert body["citations"]
    rows = [
        row
        for citation in body["citations"]
        if citation["game_id"] == game["id"]
        for row in citation["metadata"].get("rows", [])
    ]
    assert rows
    assert {citation["game_id"] for citation in body["citations"]} == {game["id"]}
    for row in rows:
        assert row["period"] == 4
        minutes, seconds = map(int, row["clock"].split(":"))
        assert minutes * 60 + seconds <= 120


async def test_best_defensive_game_binds_lowest_points_allowed_before_retrieval(
    active_seed_release,
):
    client = active_seed_release
    games = (await client.get("/games")).json()

    def allowed(game):
        return game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]

    best = min(games, key=allowed)
    response = await client.post(
        "/analysis/query", json={"question": "Explain the Knicks' best defensive game."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    assert str(allowed(best)) in body["answer"]
    assert best["game_date"] in body["answer"]
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {best["id"]}
    assert any(
        "Final scores only" in limitation
        for citation in body["citations"]
        for limitation in citation["metadata"]["claim"]["coverage_limitations"]
    )


@pytest.mark.parametrize(
    "question",
    [
        "How did the Knicks erase their largest deficit?",
        "What was the most damaging opponent run this season?",
        "What was the Knics biggest run?",
        "What was NY's worst collpase?",
    ],
)
async def test_season_run_superlative_preserves_scope_and_requests_metric(
    active_seed_release, question
):
    client = active_seed_release
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "clarify"
    assert "season-wide ranking" in body["answer"]
    assert "time window" in body["answer"]
    assert "Which game" not in body["answer"]
    assert body["citations"] == []


async def test_narrative_game_choices_disclose_truncated_dates(active_seed_release):
    from app.core.db import AsyncSessionLocal
    from app.models.dataset_release import DatasetRelease
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        release_id = (
            await db.execute(select(DatasetRelease.id).where(DatasetRelease.status == "active"))
        ).scalar_one()
        for offset in range(9):
            db.add(
                Game(
                    release_id=release_id,
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
        await db.commit()
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "Explain the Knicks game against Atlanta."}
    )
    body = response.json()
    assert body["outcome"] == "clarify"
    assert "Showing the first 8:" in body["answer"]
    assert "2026-03-01" in body["answer"]
    assert "2026-03-09" not in body["answer"]
