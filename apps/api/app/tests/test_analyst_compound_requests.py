"""Compound requests retain every requested statistic without inheriting one selector."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.services import analyst_loop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.support.analyst_protocol import local_redis as local_redis
from app.tests.support.analyst_protocol import make_tools


@pytest.mark.parametrize("with_prior", [False, True])
async def test_compound_metrics_remain_distinct(db_session, with_prior):
    previous, _ = await make_tools(db_session, "What were Brunson's average rebounds?")
    question = "What were Brunson's average points, rebounds and assists?"
    tools = AnalystTools(
        db_session,
        previous.release,
        question,
        previous.season,
        previous.state if with_prior else {},
    )
    await tools.prepare()
    for metric in ("points", "rebounds", "assists"):
        result = await tools.execute(
            ToolCall(
                name="get_player_stats",
                question=question,
                metric=metric,
                aggregation="average",
            )
        )
        assert result.status == "ok"
        assert {c.metric_id for c in result.claims} == {f"{metric}:average"}


@pytest.mark.parametrize("with_prior", [False, True])
@pytest.mark.parametrize("tool_name", ["get_player_stats", "get_team_stats"])
async def test_compound_aggregations_remain_distinct(db_session, with_prior, tool_name):
    previous, _ = await make_tools(db_session, "What were Brunson's average points?")
    question = (
        "What were Brunson's total and average points?"
        if tool_name == "get_player_stats"
        else "What were the Knicks total and average points?"
    )
    tools = AnalystTools(
        db_session,
        previous.release,
        question,
        previous.season,
        previous.state if with_prior else {},
    )
    await tools.prepare()
    found = {}
    for aggregation in ("total", "average"):
        result = await tools.execute(
            ToolCall(
                name=tool_name,
                question=question,
                metric="points",
                aggregation=aggregation,
            )
        )
        assert result.status == "ok"
        key = (
            f"points:{aggregation}"
            if tool_name == "get_player_stats"
            else "points"
            if aggregation == "total"
            else "points_per_game"
        )
        claim = next((c for c in result.claims if c.metric_id == key), None)
        assert claim is not None, [c.metric_id for c in result.claims]
        found[aggregation] = claim
    assert found["average"].value == pytest.approx(
        found["total"].value / found["average"].sample_size
    )


@pytest.mark.parametrize("tool_name", ["get_player_stats", "compare_windows"])
async def test_team_only_metric_is_an_unsupported_player_scope(db_session, tool_name):
    tools, _ = await make_tools(db_session, "What was Brunson's average scoring margin?")
    result = await tools.execute(
        ToolCall(
            name=tool_name,
            question=tools.question,
            metric="plus_minus",
            aggregation="average",
            baseline_question="Brunson in January" if tool_name == "compare_windows" else None,
        )
    )
    assert result.status == "unsupported_metric_or_scope"
    assert not result.claims


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "What were Brunson's average points, rebounds and assists?",
            {"points:average", "rebounds:average", "assists:average"},
        ),
        (
            "What were Brunson's total and average points?",
            {"points:total", "points:average"},
        ),
    ],
)
async def test_compound_request_keeps_all_requested_facts_when_model_fails(
    client, local_redis, monkeypatch, question, expected
):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        await make_tools(db)

    class UnavailableProvider:
        max_tokens = 0

        async def generate(self, *, system, user):
            raise RuntimeError("Model unavailable")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", UnavailableProvider)
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "turn_id": "compound-public-fallback-0001",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state_committed"] and body["degraded"]
    delivered = {
        c["metadata"]["claim"]["metric_id"]
        for c in body["citations"]
        if c.get("metadata", {}).get("claim")
    }
    assert expected <= delivered


async def test_compound_scope_refuses_an_unrequested_metric(db_session):
    tools, _ = await make_tools(db_session, "What were Brunson's average points and assists?")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="steals",
            aggregation="average",
        )
    )
    assert result.status == "unsupported_metric_or_scope"
    assert not result.claims
