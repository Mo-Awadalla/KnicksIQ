"""Conversation continuity and fact authority across analyst boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.services import analyst_loop
from app.services.analyst_loop import AnalystLoop
from app.services.evidence_contracts import (
    Action,
    AnswerReview,
    AssertionReview,
    ClaimUse,
    ProposedAnswer,
    ToolCall,
    split_review_spans,
)
from app.tests.support.analyst_protocol import local_redis as local_redis
from app.tests.support.analyst_protocol import make_tools
from app.tests.support.player_archive import _seed_release_stats


@pytest.mark.parametrize("interlude", ["Hello", "Which parlay should I bet on?"])
async def test_early_reply_preserves_session_topic(client, local_redis, monkeypatch, interlude):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    first = (
        await client.post(
            "/analysis/query",
            json={
                "question": "What was Brunson's average points?",
                "turn_id": "boundary-first-0001",
            },
        )
    ).json()
    assert first["state_committed"]
    interlude_request = {
        "question": interlude,
        "turn_id": "boundary-interlude-0002",
        "session_token": first["session_token"],
        "expected_revision": first["revision"],
    }
    middle = (await client.post("/analysis/query", json=interlude_request)).json()
    assert middle["state_committed"], middle
    assert middle["session_token"] == first["session_token"]
    assert middle["revision"] == first["revision"] + 1
    replay = await client.post("/analysis/query", json=interlude_request)
    assert replay.json() == middle
    conflict = await client.post(
        "/analysis/query", json={**interlude_request, "question": "Hi there"}
    )
    assert conflict.status_code == 409
    last = (
        await client.post(
            "/analysis/query",
            json={
                "question": "And his assists?",
                "turn_id": "boundary-followup-0003",
                "session_token": middle["session_token"],
                "expected_revision": middle["revision"],
            },
        )
    ).json()
    assert last["state_committed"] and last["revision"] == middle["revision"] + 1
    assert "Brunson" in last["answer"] and "assists" in last["answer"]
    assert "Which" not in last["answer"]


@pytest.mark.parametrize("interlude", ["Hello", "Which parlay should I bet on?"])
async def test_early_reply_enforces_session_revision(client, local_redis, monkeypatch, interlude):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(get_settings(), "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    first = (
        await client.post(
            "/analysis/query",
            json={
                "question": "What was their record?",
                "turn_id": "boundary-revision-0001",
            },
        )
    ).json()
    response = await client.post(
        "/analysis/query",
        json={
            "question": interlude,
            "turn_id": "boundary-stale-0002",
            "session_token": first["session_token"],
            "expected_revision": 0,
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize("tool_name", ["get_player_stats", "compare_windows"])
async def test_model_cannot_override_requested_player_metric(db_session, tool_name):
    tools, _ = await make_tools(db_session, "How many points did Brunson average?")
    result = await tools.execute(
        ToolCall(
            name=tool_name,
            question=tools.question,
            metric="assists",
            aggregation="average",
            baseline_question="Brunson points in January"
            if tool_name == "compare_windows"
            else None,
        )
    )
    assert result.status == "ok"
    assert result.claims
    assert all(claim.metric_id.startswith("points:") for claim in result.claims)


@pytest.mark.parametrize(
    "requested,proposed,metric_suffix",
    [
        ("total", "average", ":total"),
        ("average", "total", ":average"),
    ],
)
async def test_model_cannot_override_requested_aggregation(
    db_session, requested, proposed, metric_suffix
):
    tools, _ = await make_tools(db_session, f"What were Brunson's {requested} assists?")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="assists",
            aggregation=proposed,
        )
    )
    assert result.status == "ok"
    assert result.claims
    assert all(claim.metric_id == f"assists{metric_suffix}" for claim in result.claims)


async def test_unrequested_metric_remains_available_for_model_selection(db_session):
    tools, _ = await make_tools(db_session, "Tell me about Brunson")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="assists",
            aggregation="average",
        )
    )
    assert result.status == "ok"
    assert result.claims[0].metric_id == "assists:average"


async def test_unreferenced_claim_cannot_authorize_factual_answer(
    db_session, local_redis, monkeypatch
):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session, "What was Brunson's average points?")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="points",
            aggregation="average",
        )
    )
    loop = AnalystLoop(tools, [])
    loop.results.append(result)
    loop.payload(Action)
    claim = result.claims[0]
    answer = ProposedAnswer(text=claim.statement)

    async def supported_by_undeclared_claim(*_args, **_kwargs):
        return AnswerReview(
            assertions=[
                AssertionReview(
                    text=span,
                    assertion_type="factual",
                    verdict="supported",
                    offending_text=None,
                    supporting_claim_ids=[claim.claim_id],
                    supporting_evidence_ids=[],
                    reason="The value occurs in a supplied claim.",
                )
                for span in split_review_spans(answer.text)
            ]
        )

    monkeypatch.setattr(loop, "review", supported_by_undeclared_claim)
    accepted, _ = await loop.validate(answer)
    assert not accepted


async def test_declared_fact_is_reviewed_without_unrelated_evidence(
    db_session, local_redis, monkeypatch
):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session, "What was Brunson's average points?")
    points = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="points",
            aggregation="average",
        )
    )
    loop = AnalystLoop(tools, [])
    loop.results.append(points)
    loop.payload(Action)
    claim = points.claims[0]
    answer = ProposedAnswer(
        text=claim.statement,
        claims=[
            ClaimUse(
                claim_id=claim.claim_id,
                displayed_value=claim.value,
            )
        ],
    )
    captured = []

    class Reviewer:
        max_tokens = 0
        last_metadata = {"usage": {"cost": 0}}

        async def generate(self, *, system, user):
            payload = json.loads(user)
            captured.append(payload)
            answer = analyst_loop.payload_proposed_answer(payload)
            assert answer is not None
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "assertions": [
                            {
                                "text": span,
                                "assertion_type": "factual",
                                "verdict": "supported",
                                "offending_text": None,
                                "supporting_claim_ids": [
                                    item["claim_id"] for item in answer["claims"]
                                ],
                                "supporting_evidence_ids": [],
                                "reason": "Matches the declared fact.",
                            }
                            for span in payload["review_spans"]
                        ]
                    },
                )
            )

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", Reviewer)
    accepted, reason = await loop.validate(answer)
    assert accepted, reason
    assert {c["claim_id"] for c in analyst_loop.payload_claims(captured[0])} == {claim.claim_id}
    assert {e["evidence_id"] for e in captured[0]["evidence"]} <= set(claim.supporting_evidence_ids)
