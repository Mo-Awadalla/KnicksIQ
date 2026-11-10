"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

import pytest
from app.api import analysis
from app.api import analysis_policy as runtime
from app.services.llm_planner import PlannerResult
from app.tests.analysis_test_support import active_seed_release as active_seed_release
from app.tests.analysis_test_support import (
    isolate_response_cache as isolate_response_cache,
)
from starlette.requests import Request


def test_client_identity_ignores_untrusted_forwarded_header():
    def request(forwarded_for: bytes) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/analysis/query",
                "headers": [(b"x-forwarded-for", forwarded_for)],
                "client": ("203.0.113.10", 50000),
                "server": ("test", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    assert runtime._client_id(request(b"198.51.100.1")) == runtime._client_id(
        request(b"198.51.100.2")
    )


async def test_public_analysis_query_returns_citations(active_seed_release):
    r = await active_seed_release.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["data_version"] == "narrative-seed-test"
    assert body["citations"]
    assert {c["game_id"] for c in body["citations"]} == {2}
    assert "112" in body["answer"] and "95" in body["answer"]
    assert "TOR" in body["answer"]
    assert "over 1 archived games" not in body["answer"]


async def test_named_opponent_query_cannot_be_reinterpreted_as_table_rag(
    active_seed_release, monkeypatch
):
    async def table_planner(*_args, **_kwargs):
        return PlannerResult(
            intent="season_table",
            confidence=0.99,
            route="table_rag",
        )

    monkeypatch.setattr(analysis, "maybe_plan_query", table_planner)

    r = await active_seed_release.post(
        "/analysis/query",
        json={
            "question": "What happened in the Knicks game against Toronto?",
            "context": [
                {
                    "role": "user",
                    "content": "I want to review an archived Knicks matchup.",
                },
                {
                    "role": "assistant",
                    "content": "Which opponent should I use?",
                },
            ],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {2}


async def test_public_analysis_refuses_live_questions(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "Are the Knicks winning live tonight?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True
    assert body["citations"] == []
    assert body["warnings"]


async def test_public_analysis_refuses_future_player_analytics_before_historical_fallback(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "Will Jalen Brunson average 30 points tomorrow?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True
    assert body["analytics"] is None
    assert body["citations"] == []


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "question",
    ["can the knicks solve a two sum leetcode problem", "Why are Knicks jerseys blue and orange?"],
)
async def test_public_analysis_refuses_off_topic_knicks_questions(
    active_seed_release, monkeypatch, enabled, question
):
    monkeypatch.setattr(runtime.get_settings(), "analyst_evidence_loop_enabled", enabled)
    r = await active_seed_release.post("/analysis/query", json={"question": question})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True
    assert body["outcome"] == "refuse"
    assert body["citations"] == []


@pytest.mark.parametrize("enabled", [False, True])
async def test_missing_archive_data_is_not_replaced_by_season_facts(
    active_seed_release, monkeypatch, enabled
):
    monkeypatch.setattr(runtime.get_settings(), "analyst_evidence_loop_enabled", enabled)
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "Show Knicks possessions not in the data."}
    )
    assert response.status_code == 200
    body = response.json()
    assert not body["citations"]
    assert "available" in body["answer"].lower()


@pytest.mark.parametrize("enabled", [False, True])
async def test_closest_game_narrative_selects_the_actual_game(
    active_seed_release, monkeypatch, enabled
):
    monkeypatch.setattr(runtime.get_settings(), "analyst_evidence_loop_enabled", enabled)
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "What happened in the Knicks closest game?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "answer"
    assert "ATL" in body["answer"] and "108" in body["answer"] and "105" in body["answer"]
    assert body["citations"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_closest_game_tie_requires_a_choice(active_seed_release, monkeypatch, enabled):
    from datetime import date

    from app.core.db import AsyncSessionLocal
    from app.models.dataset_release import DatasetRelease
    from app.models.game import Game
    from sqlalchemy import select

    monkeypatch.setattr(runtime.get_settings(), "analyst_evidence_loop_enabled", enabled)
    async with AsyncSessionLocal() as db:
        release_id = (
            await db.execute(select(DatasetRelease.id).where(DatasetRelease.status == "active"))
        ).scalar_one()
        db.add(
            Game(
                release_id=release_id,
                nba_game_id="closest-tie",
                season="2025-26",
                game_date=date(2026, 4, 4),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=100,
                away_score=97,
                status="final",
                season_type="regular",
            )
        )
        await db.commit()
    response = await active_seed_release.post(
        "/analysis/query", json={"question": "What happened in the Knicks closest game?"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["outcome"] == "clarify"
    assert not body["citations"]


async def test_public_analysis_aggregate_uses_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "What is the Knicks record this season?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evidence"]
    assert "NYK is" in body["answer"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was the Knicks average score this season?", "112.8"),
        ("How many total points did the Knicks score this season?", "564"),
    ],
)
async def test_public_scoring_aggregates_use_the_full_archive(
    active_seed_release, question, expected
):
    response = await active_seed_release.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    assert expected in response.json()["answer"]


async def test_public_analysis_losing_streak_uses_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "When was the longest losing streak?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert "longest 2025-26 losing streak in the available data" in body["answer"]


async def test_public_analysis_best_game_uses_largest_win_margin(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "what was the knicks biggest game this season"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "by win margin" in body["answer"]
    assert "136-96" in body["answer"]


async def test_public_analysis_why_pick_follow_up_stays_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={
            "question": "why did you pick those games",
            "context": [
                {
                    "role": "user",
                    "content": "what was the knicks biggest game this season",
                },
                {
                    "role": "assistant",
                    "content": (
                        "The Knicks' best 2025-26 game by win margin in the available data was "
                        "2026-04-03 against CHI: NYK won 136-96 by 40."
                    ),
                },
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "ranks available Knicks wins by final margin" in body["answer"]


async def test_public_analysis_follow_up_uses_short_context(active_seed_release):
    r = await active_seed_release.post(
        "/analysis/query",
        json={
            "question": "What about Q4?",
            "context": [
                {
                    "role": "user",
                    "content": "What happened in the Knicks game against Toronto?",
                },
                {
                    "role": "assistant",
                    "content": "The Knicks beat Toronto using available evidence.",
                },
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["outcome"] == "clarify"
    assert not body["citations"]


async def test_public_analysis_retrieval_answer_shows_evidence(active_seed_release):
    r = await active_seed_release.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {2}
    assert body["data_version"] == "narrative-seed-test"


async def test_public_analysis_unsupported_table_question_is_not_generic_dump(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "Who had the most steals for the Knicks?"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert "No complete player steals facts are available" in body["answer"]
    assert "Available season summary" not in body["answer"]
    assert "Cached table summary" not in body["answer"]
    assert "Evidence used:" not in body["answer"]
    assert "cached" not in body["answer"].lower()
    assert body["warnings"]


async def test_public_analysis_accepts_short_greeting(client):
    response = await client.post(
        "/analysis/query",
        json={"question": "hi"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "greeting"
    assert body["answer"].startswith("Hi")
    assert body["citations"] == []


async def test_public_analysis_rejects_blank_question(client):
    response = await client.post(
        "/analysis/query",
        json={"question": "  "},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("invalid_date", ["2025-02-30", "2025-13-01", "2025-00-10"])
async def test_invalid_calendar_dates_are_rejected(client, invalid_date):
    response = await client.post(
        "/analysis/query",
        json={"question": f"What happened in the Knicks game on {invalid_date}?"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_invalid_calendar_date_in_follow_up_context_is_rejected(client):
    response = await client.post(
        "/analysis/query",
        json={
            "question": "What about the fourth quarter?",
            "context": [{"role": "user", "content": "Knicks game on 2025-02-30"}],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("question", "verb"),
    [
        ("How many games did the Knicks win?", "won"),
        ("How many games did the Knicks lose?", "lost"),
    ],
)
async def test_game_result_counts_answer_the_requested_metric(client, question, verb):
    games = (await client.get("/games")).json()
    wins = sum(game["winner_team_id"] == "NYK" for game in games)
    expected = wins if verb == "won" else len(games) - wins
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    assert f"{verb} {expected} of {len(games)}" in response.json()["answer"]
