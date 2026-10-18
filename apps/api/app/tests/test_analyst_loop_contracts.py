"""Analyst bounded orchestration, provider fallback and repair contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.services import analyst_provider
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import (
    ToolCall,
)
from app.tests.support.analyst_protocol import (
    ScriptedAdapter,
    make_tools,
)
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)


async def test_bounded_loop_and_revalidated_explanation(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    loop = AnalystLoop(tools, [])
    response = await loop.run()
    assert response["llm_validated"], response
    assert loop.calls == 3 and loop.rounds == 1
    assert response["citations"]
    assert response["state"]["delivered_fact_ids"]
    assert "context" not in adapter.prompts[-1]
    followup = AnalystTools(
        db_session,
        tools.release,
        "Why is that interesting?",
        tools.release.season,
        response["state"],
    )
    await followup.prepare()
    loop2 = AnalystLoop(followup, [])
    result = await loop2.run()
    assert result["llm_validated"] and loop2.calls == 2 and loop2.rounds == 0


async def test_ten_short_prior_messages_still_reach_writer(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    context = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"Turn {index}"}
        for index in range(10)
    ]
    result = await AnalystLoop(tools, context).run()
    assert result["llm_validated"], result
    assert adapter.prompts[0]["context"] == context


async def test_provider_schema_growth_uses_factual_fallback(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    monkeypatch.setattr(get_settings(), "analyst_provider_format", "json_schema")
    tools, _ = await make_tools(db_session)

    class SchemaAdapter(ScriptedAdapter):
        response_schema: dict | None = None

    adapter = SchemaAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    result = await AnalystLoop(tools, []).run()
    assert not result["llm_validated"]
    assert len(adapter.prompts) == 1
    assert result["answer"]


async def test_bad_provider_output_counts_call_and_falls_back(
    db_session, local_redis, monkeypatch, caplog
):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)

    class BadAdapter:
        async def generate(self, **kwargs):
            return '{"action":"invented"}'

    monkeypatch.setattr(analyst_provider, "get_llm_adapter", BadAdapter)
    loop = AnalystLoop(tools, [])
    result = await loop.run()
    assert not result["llm_validated"] and loop.calls == 1
    failure = next(r for r in caplog.records if r.message.startswith("analyst_execution_failed"))
    assert failure.error_type == "ValidationError"
    assert failure.model_calls == 1
    assert "invented" not in caplog.text
    assert result["citations"] and result["state"]["delivered_fact_ids"]


async def test_release_change_drops_old_claims_and_scope_transition(db_session):
    tools, player = await make_tools(db_session, "Brunson points")
    result = await tools.execute(ToolCall(name="get_player_stats", question=tools.question))
    state = {
        "release": "superseded",
        "claims": [c.model_dump() for c in result.claims],
        "evidence": [e.model_dump() for e in result.evidence],
        "scope": {"player_ids": [player.id]},
        "delivered_fact_ids": ["old"],
    }
    current = AnalystTools(
        db_session, tools.release, "Now only playoff games", tools.release.season, state
    )
    await current.prepare()
    assert not current.claims and not current.evidence
    assert current.scope is not None
    assert current.scope.player_ids == [player.id]
    assert current.scope.season_type == "playoffs"
    assert not current.state["delivered_fact_ids"]


@pytest.mark.parametrize("request_timeout", [1.0, 20.0])
async def test_repair_is_rechecked_and_never_investigates(
    db_session, local_redis, monkeypatch, request_timeout
):
    monkeypatch.setattr(get_settings(), "ai_request_timeout_seconds", request_timeout)
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)

    class RepairAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            if payload["schema"]["title"] == "ProposedAnswer":
                self.prompts.append(payload)
                answer = payload["proposed_answer"]
                answer["text"] = answer["text"].replace(" A new tactic caused this.", "")
                return json.dumps(answer)
            raw = await super().generate(system=system, user=user)
            value = json.loads(raw)
            if payload["schema"]["title"] == "Action" and value.get("answer"):
                value["answer"]["text"] += " A new tactic caused this."
            if (
                payload["schema"]["title"] == "AnswerReview"
                and "tactic" in payload["proposed_answer"]["text"]
            ):
                value["assertions"][0].update(
                    verdict="unsupported",
                    offending_text="A new tactic caused this.",
                    reason="No causal source.",
                )
            return json.dumps(value)

    adapter = RepairAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    loop = AnalystLoop(tools, [])
    result = await loop.run()
    assert result["llm_validated"], result
    assert "tactic" not in result["answer"]
    assert loop.calls == 5 and loop.rounds == 1
    assert [p["schema"]["title"] for p in adapter.prompts][-2:] == [
        "ProposedAnswer",
        "AnswerReview",
    ]
