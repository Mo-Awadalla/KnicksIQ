"""Tests for public analyst query endpoint."""

from __future__ import annotations

from app.api import analysis


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
    assert "Evidence used:" in body["answer"]
    tools = {call["tool"] for call in body["tool_calls"]}
    assert tools == {"table_rag"}


async def test_public_analysis_losing_streak_uses_table_rag(client):
    r = await client.post(
        "/analysis/query",
        json={"question": "what was the knicks longest losing streak"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert body["classifier"]["is_aggregative"] is True
    assert "longest cached 2025-26 losing streak" in body["answer"]
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
                        "The Knicks' best cached 2025-26 game by win margin was "
                        "2026-04-03 against CHI: NYK won 136-96 by 40."
                    ),
                },
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "table_rag"
    assert "because this route ranks cached Knicks wins by final margin" in body["answer"]
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
                    "content": "The Knicks beat Toronto using cached evidence.",
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
    assert "Evidence used:" in body["answer"]


async def test_public_analysis_query_uses_configured_llm(client, monkeypatch):
    class StubSettings:
        ai_provider = "openrouter"
        ai_api_key = "test-key"
        ai_chat_model = "poolside/laguna-xs-2.1:free"
        public_chat_rate_limit_per_minute = 20
        public_chat_max_prompt_chars = 1200

    class StubAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            assert "grounded Knicks analyst" in system
            assert "Toronto" in user
            return "LLM-grounded Raptors answer."

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
    assert body["answer"].startswith("LLM-grounded Raptors answer.")
    assert "Evidence used:" in body["answer"]
    assert {"tool": "llm_generate", "model": "poolside/laguna-xs-2.1:free"} in body[
        "tool_calls"
    ]


async def test_public_analysis_valid_question_recovers_after_off_topic_context(client):
    context = [
        {
            "role": "user",
            "content": "who are you",
        },
        {
            "role": "assistant",
            "content": (
                "I can only answer grounded questions about cached Knicks 2025-26 "
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
                "I can only answer grounded questions about cached Knicks 2025-26 "
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
                "I can only answer grounded questions about cached Knicks 2025-26 "
                "regular-season or playoff games."
            ),
        },
    ]

    r = await client.post(
        "/analysis/query",
        json={
            "question": "who beat the knicks by the most points",
            "context": context,
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["route"] == "table_rag"
    assert "biggest cached 2025-26 Knicks loss" in body["answer"]
    assert body["tool_calls"]
