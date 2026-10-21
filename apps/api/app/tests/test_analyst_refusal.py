"""The API's refusal flag must reflect what the model actually did.

Declines can contain related archive facts, clarifications and conversational
replies are not declines, and a deterministic fallback is a degraded answer
unless the fallback itself states that the requested data is unavailable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.services import analyst_provider
from app.services.analyst_loop import AnalystLoop
from app.services.evidence_contracts import ToolCall
from app.tests.support.analyst_protocol import (
    ScriptedAdapter,
    make_tools,
)
from app.tests.support.analyst_protocol import (
    local_redis as local_redis,
)


class DeclaredAdapter(ScriptedAdapter):
    def __init__(self, action: str, text: str, *, claims: int = 0, review_type: str = "coverage"):
        super().__init__()
        self.action, self.text, self.claim_count = action, text, claims
        self.review_type = review_type

    async def generate(self, *, system, user):
        payload = json.loads(user)
        if payload["schema"]["title"] == "AnswerReview":
            answer = payload["proposed_answer"]
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": span,
                            "assertion_type": self.review_type,
                            "verdict": "supported",
                            "offending_text": None,
                            "supporting_claim_ids": [
                                claim["claim_id"] for claim in answer["claims"]
                            ],
                            "supporting_evidence_ids": [],
                            "reason": "Fixture supports the declared intent.",
                        }
                        for span in payload["review_spans"]
                    ]
                }
            )
        self.prompts.append(payload)
        candidate = next(iter(payload["candidates"]), None)
        used = (
            [claim for claim in payload["claims"] if claim["claim_id"] in candidate["claim_ids"]]
            if candidate and self.claim_count
            else payload["claims"][: self.claim_count]
        )
        text = self.text.format(statement=used[0]["statement"] if used else "No archive fact.")
        return json.dumps(
            {
                "action": self.action,
                "tools": [],
                "answer": {
                    "text": text,
                    "claims": [
                        {"claim_id": claim["claim_id"], "displayed_value": claim["value"]}
                        for claim in used
                    ],
                    "evidence_ids": [],
                    "fact_ids": [candidate["fact_id"]] if candidate and used else [],
                },
            }
        )


class FailingAdapter:
    max_tokens = 0
    last_metadata = {"usage": {"cost": 0}, "provider": "protocol-fixture"}

    async def generate(self, *, system, user):
        raise RuntimeError("provider unavailable")


async def test_decline_with_partial_facts_is_refused(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    adapter = DeclaredAdapter(
        "decline",
        "I can't predict the next game. Related archive fact: {statement}",
        claims=1,
    )
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    loop = AnalystLoop(tools, [])
    loop.results.append(result)
    result = await loop.run()
    assert result["llm_validated"], result
    assert result["refused"] is True
    assert result["citations"]


@pytest.mark.parametrize(
    ("action", "text", "review_type"),
    [
        ("ask_clarification", "Which Boston game do you mean?", "conversational"),
        (
            "answer_from_available_evidence",
            "You're welcome. Ask me about another game.",
            "conversational",
        ),
    ],
)
async def test_non_declines_are_not_refused(
    db_session, local_redis, monkeypatch, action, text, review_type
):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    adapter = DeclaredAdapter(action, text, review_type=review_type)
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    result = await AnalystLoop(tools, []).run()
    assert result["llm_validated"], result
    assert result["refused"] is False


async def test_explained_coverage_is_refused(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    adapter = DeclaredAdapter(
        "explain_coverage",
        "I can't provide live injury data. The archive covers 2025-26 game records.",
        review_type="coverage",
    )
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    result = await AnalystLoop(tools, []).run()
    assert result["llm_validated"], result
    assert result["refused"] is True


async def test_fallback_answer_is_not_refused(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", FailingAdapter)
    result = await AnalystLoop(tools, []).run()
    assert not result["llm_validated"]
    assert result["citations"]
    assert result["refused"] is False


async def test_fallback_on_unavailable_live_question_is_refused(
    db_session, local_redis, monkeypatch
):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session, "Who is injured today?")
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", FailingAdapter)
    result = await AnalystLoop(tools, []).run()
    assert not result["llm_validated"]
    assert result["refused"] is True
