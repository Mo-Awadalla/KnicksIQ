"""Public analyst endpoint cases grouped by behavior."""

from __future__ import annotations

import json

from app.api import analysis
from app.api import analysis_generation as generation
from app.api import analysis_player_response as player_response
from app.api import analysis_policy as runtime
from app.api import analysis_retrieval as retrieval
from app.services import analyst_provider
from app.services.archive_retrieval import ArchiveEvidence
from app.services.player_analytics import AnalyticsAnswer
from app.tests.analysis_test_support import (
    _true,
)
from app.tests.analysis_test_support import active_seed_release as active_seed_release
from app.tests.analysis_test_support import (
    isolate_response_cache as isolate_response_cache,
)


async def test_deterministic_mode_does_not_use_configured_llm(active_seed_release, monkeypatch):
    settings = runtime.get_settings()
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")

    class StubAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            raise AssertionError("deterministic mode must not call the model")

    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: StubAdapter())
    monkeypatch.setattr(
        generation,
        "get_llm_adapter",
        lambda *, response_format_json=True: StubAdapter(),
    )

    r = await active_seed_release.post(
        "/analysis/query",
        json={"question": "What happened in the Knicks game against Toronto?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["citations"]
    assert {citation["game_id"] for citation in body["citations"]} == {2}
    assert "112" in body["answer"] and "95" in body["answer"]


async def test_llm_primary_synthesizes_computed_swing_facts(client, monkeypatch):
    original_settings = runtime.get_settings()

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

    monkeypatch.setattr(runtime, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(generation, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        generation,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(
        retrieval,
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


async def test_llm_primary_planner_can_accept_unfamiliar_archive_phrasing(client, monkeypatch):
    original_settings = runtime.get_settings()

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

    monkeypatch.setattr(runtime, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(analysis, "maybe_plan_retrieval", accepted_plan)
    monkeypatch.setattr(generation, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(
        generation,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(
        retrieval,
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
    original_settings = runtime.get_settings()

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

    monkeypatch.setattr(runtime, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(generation, "reserve_ai_budget", lambda: _true())
    monkeypatch.setattr(player_response, "answer_player_question", player_answer)
    monkeypatch.setattr(
        generation,
        "get_llm_adapter",
        lambda *, response_format_json=True: GroundedAdapter(),
    )
    monkeypatch.setattr(retrieval, "search_archive_vectors", lambda **_kwargs: [])

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


async def test_conditional_generation_never_calls_model_for_structured_question(
    client,
    monkeypatch,
):
    original_settings = runtime.get_settings()

    class ConditionalSettings:
        analysis_answer_mode = "llm_primary"
        rag_conditional_generation_enabled = True
        rag_qdrant_enabled = False
        test_mode = False
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "approved-model"
        openrouter_allowed_models = ["approved-model"]

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def healthy_rate_limit(_request):
        return False

    def fail_adapter(**_kwargs):
        raise AssertionError("structured questions must not call generation")

    monkeypatch.setattr(runtime, "get_settings", lambda: ConditionalSettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(generation, "get_llm_adapter", fail_adapter)

    response = await client.post(
        "/analysis/query",
        json={"question": "What was the Knicks average score?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert "llm_generate" not in {call["tool"] for call in body["tool_calls"]}
    assert "deterministic_retrieval_plan" in {call["tool"] for call in body["tool_calls"]}


async def test_llm_primary_qdrant_failure_uses_deterministic_swing_answer(
    client,
    monkeypatch,
):
    original_settings = runtime.get_settings()

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

    cache_writes = []

    async def capture_cache_write(key, value):
        cache_writes.append((key, value))

    monkeypatch.setattr(runtime, "get_settings", lambda: LlmPrimarySettings())
    monkeypatch.setattr(analysis, "_rate_limit", healthy_rate_limit)
    monkeypatch.setattr(retrieval, "search_archive_vectors", failed_search)
    monkeypatch.setattr(analysis, "set_cached_answer", capture_cache_write)
    monkeypatch.setattr(
        generation,
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
    assert cache_writes == []
