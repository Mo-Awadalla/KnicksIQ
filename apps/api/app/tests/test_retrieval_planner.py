"""Behavioral contract for bounded LLM retrieval plans."""

from __future__ import annotations

import pytest
from app.services import retrieval_planner
from app.services.retrieval_planner import (
    RetrievalPlan,
    deterministic_retrieval_plan,
    maybe_plan_retrieval,
)
from pydantic import ValidationError


def test_retrieval_plan_rejects_unknown_collections():
    with pytest.raises(ValidationError):
        RetrievalPlan.model_validate(
            {
                "supported": True,
                "intent": "descriptive",
                "queries": ["What happened against Toronto?"],
                "collections": ["private_notes"],
                "filters": {},
                "fact_tools": [],
            }
        )


def test_retrieval_plan_cannot_override_release_scope():
    with pytest.raises(ValidationError):
        RetrievalPlan.model_validate(
            {
                "supported": True,
                "intent": "descriptive",
                "queries": ["What happened against Toronto?"],
                "collections": ["games"],
                "filters": {"data_version": "unreviewed-release"},
                "fact_tools": [],
            }
        )


async def test_llm_plan_cannot_invent_a_playoff_filter(monkeypatch):
    fallback = deterministic_retrieval_plan(
        "What were the Knicks season turning points?",
        intent="descriptive",
        is_aggregative=False,
    )

    class Settings:
        rag_llm_planner_enabled = True
        ai_provider = "openrouter"
        ai_api_key = "test-key"

    class Adapter:
        async def generate(self, *, system: str, user: str) -> str:
            return (
                '{"supported":true,"intent":"descriptive",'
                '"queries":["Knicks playoff turning points"],'
                '"collections":["games","reports"],'
                '"filters":{"season_types":["playoffs"]},'
                '"fact_tools":[]}'
            )

    monkeypatch.setattr(retrieval_planner, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        retrieval_planner,
        "get_llm_adapter",
        lambda *, response_format_json=True: Adapter(),
    )

    assert (
        await maybe_plan_retrieval(
            "What were the Knicks season turning points?",
            fallback=fallback,
        )
        == fallback
    )


async def test_llm_planner_budget_denial_returns_fallback(monkeypatch):
    fallback = deterministic_retrieval_plan(
        "Which games had the wildest swings?",
        intent="aggregative",
        is_aggregative=True,
    )

    class Settings:
        rag_llm_planner_enabled = True
        ai_provider = "openrouter"
        ai_api_key = "test-key"

    class UnexpectedAdapter:
        async def generate(self, *, system: str, user: str) -> str:
            raise AssertionError("budget denial must prevent the planner call")

    async def denied(*_args, **_kwargs):
        return False

    monkeypatch.setattr(retrieval_planner, "get_settings", lambda: Settings())
    monkeypatch.setattr(retrieval_planner, "reserve_ai_budget", denied)
    monkeypatch.setattr(
        retrieval_planner,
        "get_llm_adapter",
        lambda *, response_format_json=True: UnexpectedAdapter(),
    )

    assert (
        await maybe_plan_retrieval(
            "Which games had the wildest swings?",
            fallback=fallback,
        )
        == fallback
    )
