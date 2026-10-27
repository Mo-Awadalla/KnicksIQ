"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.api import analysis
from app.api import analysis_policy as runtime
from app.api import analysis_retrieval as retrieval
from app.models.game import Game
from app.services.llm_planner import PlannerResult
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


async def test_matching_games_finds_named_opponent_beyond_latest_ten(db_session):
    for offset in range(11):
        db_session.add(
            Game(
                nba_game_id=f"later-boston-{offset}",
                season="2025-26",
                game_date=date(2026, 4, 13) + timedelta(days=offset),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=110,
                away_score=100,
                status="final",
                season_type="playoffs",
                data_status="summary_only",
            )
        )
    await db_session.commit()

    games = await retrieval._matching_games(
        db_session,
        "What happened in the Knicks game against Toronto?",
        "2025-26",
    )

    assert games
    assert all("TOR" in {game.home_team_id, game.away_team_id} for game in games)


async def test_public_analysis_query_returns_citations(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "retrieval_rag"
    assert body["classifier"]["kind"] == "descriptive"
    assert "evidence" in body
    assert "warnings" in body
    assert "Knicks" in body["answer"]
    assert body["citations"]
    assert any(c["type"] == "game" for c in body["citations"])


async def test_named_opponent_query_cannot_be_reinterpreted_as_table_rag(client, monkeypatch):
    async def table_planner(*_args, **_kwargs):
        return PlannerResult(
            intent="season_table",
            confidence=0.99,
            route="table_rag",
        )

    monkeypatch.setattr(analysis, "maybe_plan_query", table_planner)

    r = await client.post(
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
    assert body["route"] == "retrieval_rag"
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {2}
    assert all(
        "TOR" in citation["title"] for citation in body["citations"] if citation["type"] == "game"
    )


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


async def test_public_analysis_refuses_off_topic_knicks_questions(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "can the knicks solve a two sum leetcode problem"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True
    assert body["route"] is None
    assert body["citations"] == []
    assert body["tool_calls"] == []


async def test_public_analysis_best_game_uses_largest_win_margin(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "what was the knicks biggest game this season"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "table_rag"
    assert body["classifier"]["is_aggregative"] is True
    assert "136-96" in body["answer"]


async def test_public_analysis_accepts_pronoun_biggest_win_query(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "what was their biggest win"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert "best 2025-26 game by win margin" in body["answer"]
    assert "136-96" in body["answer"]
    assert "cached" not in body["answer"].lower()


async def test_public_analysis_follow_up_uses_short_context(client):
    r = await client.post(
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
    assert body["route"] == "retrieval_rag"


async def test_public_analysis_retrieval_answer_shows_evidence(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "retrieval_rag"
    assert "Short answer" in body["answer"]
    assert "Receipts" in body["answer"]
    assert "cached" not in body["answer"].lower()


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
    ("question", "required_inputs"),
    [
        (
            "How did the Knicks erase their largest deficit?",
            ["scope", "observed", "erased", "tied", "lead", "win"],
        ),
        (
            "What was the most damaging opponent run this season?",
            ["season", "boundaries", "damage"],
        ),
        ("What was the Knics biggest run?", ["unanswered", "net", "window", "scope"]),
        ("What was NY's worst collpase?", ["lead", "margin", "interval", "scope", "loss"]),
    ],
)
async def test_season_run_superlative_preserves_scope_and_requests_metric(
    client, question, required_inputs
):
    response = await client.post("/analysis/query", json={"question": question})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "clarification"
    assert all(term in body["answer"].lower() for term in required_inputs)
    assert body["citations"] == []


async def test_narrative_game_choices_include_all_archived_dates(client, db_session):
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
    games_response = await client.get("/games?team_id=ATL")
    assert games_response.status_code == 200
    expected_dates = {game["game_date"] for game in games_response.json()}
    assert {f"2026-03-{day:02d}" for day in range(1, 10)} <= expected_dates
    response = await client.post(
        "/analysis/query", json={"question": "Explain the Knicks game against Atlanta."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "clarification"
    assert body["citations"] == []
    assert all(game_date in body["answer"] for game_date in expected_dates)
