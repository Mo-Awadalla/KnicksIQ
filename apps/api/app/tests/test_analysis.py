"""Tests for public analyst query endpoint."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from app.api import analysis
from app.models.game import Game
from app.services.archive_retrieval import ArchiveEvidence
from app.services.llm_planner import PlannerResult
from app.services.player_analytics import AnalyticsAnswer
from starlette.requests import Request


@pytest.fixture(autouse=True)
def isolate_response_cache(monkeypatch):
    async def cache_miss(_key):
        return None

    async def discard_cache_write(_key, _value):
        return None

    monkeypatch.setattr(analysis, "get_cached_answer", cache_miss)
    monkeypatch.setattr(analysis, "set_cached_answer", discard_cache_write)


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

    assert analysis._client_id(request(b"198.51.100.1")) == analysis._client_id(
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

    games = await analysis._matching_games(
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


async def test_public_analysis_aggregate_uses_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "What is the Knicks record this season?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "table_rag"
    assert body["classifier"]["is_aggregative"] is True
    assert body["evidence"]
    assert "NYK is" in body["answer"]
    assert "Short answer" in body["answer"]
    assert "Key evidence" in body["answer"]
    assert "cached" not in body["answer"].lower()
    tools = {call["tool"] for call in body["tool_calls"]}
    assert tools == {"table_rag"}


async def test_public_analysis_losing_streak_uses_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "When was the longest losing streak?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert body["classifier"]["is_aggregative"] is True
    assert "longest 2025-26 losing streak in the available data" in body["answer"]
    assert {call["tool"] for call in body["tool_calls"]} == {"table_rag"}


async def test_public_analysis_best_game_uses_largest_win_margin(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "what was the knicks biggest game this season"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "table_rag"
    assert body["classifier"]["is_aggregative"] is True
    assert "by win margin" in body["answer"]
    assert "136-96" in body["answer"]
    assert {call["tool"] for call in body["tool_calls"]} == {"table_rag"}


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
    assert body["route"] == "table_rag"
    assert "ranks available Knicks wins by final margin" in body["answer"]
    assert {call["tool"] for call in body["tool_calls"]} == {"table_rag"}


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


async def test_deterministic_mode_does_not_use_configured_llm(client, monkeypatch):
    class StubSettings:
        analysis_answer_mode = "deterministic"
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
        public_chat_rate_limit_per_minute = 20
        public_chat_max_prompt_chars = 1200

    class StubAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            raise AssertionError("deterministic mode must not call the model")

    monkeypatch.setattr(analysis, "get_settings", lambda: StubSettings())
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: StubAdapter(),
    )

    r = await client.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("Short answer")
    assert "Receipts" in body["answer"]
    assert all(call["tool"] != "llm_generate" for call in body["tool_calls"])


async def test_openrouter_failure_preserves_deterministic_factual_answer(client, monkeypatch):
    original_get_settings = analysis.get_settings

    class StubSettings:
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]

    class FailingAdapter:
        async def generate(self, *, system: str, user: str) -> str:  # noqa: ARG002
            raise ConnectionError("provider unavailable")

    monkeypatch.setattr(analysis, "get_settings", lambda: StubSettings())
    monkeypatch.setattr(analysis, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: FailingAdapter(),
    )

    answer = await analysis._generate_llm_answer(
        question="What happened against Toronto?",
        season="2025-26",
        games=[],
        docs=[],
    )

    assert answer is None
    monkeypatch.setattr(analysis, "get_settings", original_get_settings)

    response = await client.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["citations"]
    assert "Knicks" in body["answer"]
    assert all(call["tool"] != "llm_generate" for call in body["tool_calls"])


async def _true() -> bool:
    return True


async def test_redis_failure_marks_factual_answer_degraded(client, monkeypatch):
    async def redis_degraded(_request):
        return True

    monkeypatch.setattr(analysis, "_rate_limit", redis_degraded)

    response = await client.post(
        "/analysis/query",
        json={"question": "What is the Knicks record this season?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["degraded"] is True
    assert body["citations"]
    assert "NYK is" in body["answer"]


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


async def test_llm_primary_synthesizes_computed_swing_facts(client, monkeypatch):
    original_settings = analysis.get_settings()

    class LlmPrimarySettings:
        analysis_answer_mode = "llm_primary"
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    class GroundedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            payload = json.loads(user)
            assert "evidence-linked claims" in system.lower()
            assert "score-margin range" in payload["evidence"]["fact:table"]
            assert payload["evidence"]["vector:possessions:swing-1"]
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": (
                                "The computed score-margin ranking identifies the wildest swings."
                            ),
                            "evidence_ids": [
                                "fact:table",
                                "vector:possessions:swing-1",
                            ],
                        }
                    ]
                }
            )

    async def healthy_rate_limit(_request):
        return False

    monkeypatch.setattr(analysis, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(analysis, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(
        analysis,
        "search_archive_vectors",
        lambda **_kwargs: [
            ArchiveEvidence(
                evidence_id="vector:possessions:swing-1",
                collection="possessions",
                text="Archive possession evidence about the wildest swings.",
                score=1.0,
                metadata={"game_id": 1},
            )
        ],
    )

    response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["answer"].startswith("The computed score-margin ranking")
    assert {call["tool"] for call in body["tool_calls"]} == {
        "retrieval_plan",
        "archive_vector_search",
        "table_rag",
        "llm_generate",
    }
    assert body["citations"]


async def test_llm_primary_grounds_descriptive_answers_in_vector_evidence(client, monkeypatch):
    original_settings = analysis.get_settings()

    class LlmPrimarySettings:
        analysis_answer_mode = "llm_primary"
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    class GroundedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            payload = json.loads(user)
            assert payload["evidence"]["vector:reports:toronto-1"]
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "Toronto was decided by the archived turning points.",
                            "evidence_ids": ["vector:reports:toronto-1"],
                        }
                    ]
                }
            )

    async def healthy_rate_limit(_request):
        return False

    monkeypatch.setattr(analysis, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(analysis, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(
        analysis,
        "search_archive_vectors",
        lambda **_kwargs: [
            ArchiveEvidence(
                evidence_id="vector:reports:toronto-1",
                collection="reports",
                text="Archived Toronto turning points.",
                score=1.0,
                metadata={"game_id": 2},
            )
        ],
    )

    response = await client.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Toronto was decided by the archived turning points."
    assert body["refused"] is False
    assert body["degraded"] is False
    assert {"retrieval_plan", "archive_vector_search", "llm_generate"}.issubset(
        {call["tool"] for call in body["tool_calls"]}
    )
    assert body["citations"]


async def test_llm_primary_planner_can_accept_unfamiliar_archive_phrasing(client, monkeypatch):
    original_settings = analysis.get_settings()

    class LlmPrimarySettings:
        analysis_answer_mode = "llm_primary"
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def healthy_rate_limit(_request):
        return False

    async def accepted_plan(_question, *, fallback):
        return fallback.model_copy(
            update={
                "supported": True,
                "intent": "descriptive",
                "queries": ["dramatic Knicks lead reversals"],
                "collections": ["reports"],
            }
        )

    class GroundedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "The archive contains dramatic lead reversals.",
                            "evidence_ids": ["vector:reports:reversal-1"],
                        }
                    ]
                }
            )

    monkeypatch.setattr(analysis, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(analysis, "maybe_plan_retrieval", accepted_plan)
    monkeypatch.setattr(analysis, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(
        analysis,
        "search_archive_vectors",
        lambda **_kwargs: [
            ArchiveEvidence(
                evidence_id="vector:reports:reversal-1",
                collection="reports",
                text="The archive contains dramatic lead reversals.",
                score=1.0,
                metadata={"game_id": 1},
            )
        ],
    )

    response = await client.post(
        "/analysis/query",
        json={"question": "Rank the craziest reversals."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["answer"] == "The archive contains dramatic lead reversals."


async def test_llm_primary_synthesizes_typed_player_analytics(client, monkeypatch):
    original_settings = analysis.get_settings()

    class LlmPrimarySettings:
        analysis_answer_mode = "llm_primary"
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def player_answer(*_args, **_kwargs):
        return AnalyticsAnswer(
            answer="Jalen Brunson averaged 25 points.",
            analytics={
                "status": "complete",
                "resolved_question": "Brunson scoring average",
                "plan": None,
                "clarification": None,
                "results": [
                    {
                        "type": "aggregate",
                        "id": "brunson-points",
                        "title": "Jalen Brunson points",
                        "raw_values": {"points": 25},
                        "display_values": {"points": "25.0"},
                        "sample_size": 2,
                        "timeframe": {"label": "last 2 appearances"},
                        "warnings": [],
                        "source_game_ids": [1, 2],
                    }
                ],
                "coverage": None,
            },
            citations=[
                {
                    "claim": "Jalen Brunson averaged 25 points.",
                    "type": "analytics",
                    "title": "Jalen Brunson points",
                    "metadata": {"result_id": "brunson-points"},
                }
            ],
            warnings=[],
        )

    class GroundedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            payload = json.loads(user)
            player_fact = json.loads(payload["evidence"]["fact:player"])
            assert player_fact["results"][0]["raw_values"]["points"] == 25
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "Brunson averaged 25 points in the computed sample.",
                            "evidence_ids": ["fact:player"],
                        }
                    ]
                }
            )

    async def healthy_rate_limit(_request):
        return False

    monkeypatch.setattr(analysis, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(analysis, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(analysis, "answer_player_question", player_answer)
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(analysis, "search_archive_vectors", lambda **_kwargs: [])

    response = await client.post(
        "/analysis/query",
        json={"question": "What did Jalen Brunson average?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Brunson averaged 25 points in the computed sample."
    assert body["analytics"]["results"][0]["raw_values"]["points"] == 25
    assert body["citations"]
    assert {call["tool"] for call in body["tool_calls"]} == {
        "player_analytics",
        "retrieval_plan",
        "archive_vector_search",
        "llm_generate",
    }


async def test_llm_primary_qdrant_failure_uses_deterministic_swing_answer(
    client,
    monkeypatch,
):
    original_settings = analysis.get_settings()

    class LlmPrimarySettings:
        analysis_answer_mode = "llm_primary"
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def healthy_rate_limit(_request):
        return False

    class UnexpectedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            raise AssertionError("LLM must not run without primary vector retrieval")

    def failed_search(**_kwargs):
        raise ConnectionError("qdrant unavailable")

    monkeypatch.setattr(analysis, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "is_qdrant_healthy", lambda: True)
    monkeypatch.setattr(analysis, "search_archive_vectors", failed_search)
    monkeypatch.setattr(
        analysis,
        "get_llm_adapter",
        lambda *, response_format_json=True: UnexpectedAdapter(),
    )

    response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["degraded"] is True
    assert "score-margin range" in body["answer"]
    assert all(call["tool"] != "llm_generate" for call in body["tool_calls"])


async def test_shadow_mode_returns_deterministic_answer_and_runs_candidate_in_background(
    client,
    monkeypatch,
):
    original_settings = analysis.get_settings()
    captured = []

    class ShadowSettings:
        analysis_answer_mode = "shadow"
        analysis_shadow_sample_rate = 1.0
        test_mode = False
        public_chat_max_prompt_chars = 1200
        rag_qdrant_enabled = True

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def healthy_rate_limit(_request):
        return False

    async def shadow_candidate(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(analysis, "get_settings", lambda: ShadowSettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(
        analysis,
        "is_qdrant_healthy",
        lambda: (_ for _ in ()).throw(
            AssertionError("shadow response must not block on Qdrant health")
        ),
    )
    monkeypatch.setattr(analysis, "_run_shadow_candidate", shadow_candidate)

    response = await client.post(
        "/analysis/query",
        json={"question": "Which games had the wildest swings?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "score-margin range" in body["answer"]
    assert {call["tool"] for call in body["tool_calls"]} == {"table_rag"}
    assert len(captured) == 1
    assert "score-margin range" in captured[0]["evidence"]["fact:table"]


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
