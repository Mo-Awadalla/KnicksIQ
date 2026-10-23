"""Public continuity and complete requested statistics on the current-main engine."""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.test_analyst_contracts import local_redis as local_redis
from app.tests.test_analyst_contracts import make_tools


@pytest.mark.parametrize("interlude", ["Hello", "Which parlay should I bet on tonight?"])
async def test_interlude_preserves_committed_player_window(
    client, local_redis, monkeypatch, interlude
):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        await make_tools(db)
    first = (
        await client.post(
            "/analysis/query",
            json={
                "question": "Brunson's average points from 2026-01-01 through 2026-01-02?",
                "turn_id": "reconciled-first-turn",
            },
        )
    ).json()
    middle_request = {
        "question": interlude,
        "turn_id": "reconciled-middle-turn",
        "session_token": first["session_token"],
        "expected_revision": first["revision"],
    }
    middle = (await client.post("/analysis/query", json=middle_request)).json()
    assert middle["state_committed"]
    assert middle["revision"] == first["revision"] + 1
    assert (await client.post("/analysis/query", json=middle_request)).json() == middle
    last = (
        await client.post(
            "/analysis/query",
            json={
                "question": "And his assists?",
                "turn_id": "reconciled-last-turn",
                "session_token": middle["session_token"],
                "expected_revision": middle["revision"],
            },
        )
    ).json()
    assert last["state_committed"]
    assert "Brunson" in last["answer"] and "assists" in last["answer"]
    assert "Which" not in last["answer"]
    first_games = {game for c in first["citations"] for game in c["metadata"]["claim"]["game_ids"]}
    last_games = {game for c in last["citations"] for game in c["metadata"]["claim"]["game_ids"]}
    assert last_games == first_games


@pytest.mark.parametrize("with_prior", [False, True])
async def test_compound_player_metrics_do_not_collapse(db_session, with_prior):
    prior, _ = await make_tools(db_session, "Brunson average rebounds")
    question = "What were Brunson's average points, rebounds and assists?"
    tools = AnalystTools(
        db_session, prior.release, question, prior.season, prior.state if with_prior else {}
    )
    await tools.prepare()
    for metric in ("points", "rebounds", "assists"):
        result = await tools.execute(
            ToolCall(
                name="get_player_stats", question=question, metric=metric, aggregation="average"
            )
        )
        assert result.status == "ok", result.message
        assert {c.metric_id for c in result.claims} == {f"{metric}:average"}


async def test_total_and_average_are_both_available(db_session):
    tools, _ = await make_tools(db_session, "What were Brunson's total and average points?")
    observed = {}
    for aggregation in ("total", "average"):
        result = await tools.execute(
            ToolCall(
                name="get_player_stats",
                question=tools.question,
                metric="points",
                aggregation=aggregation,
            )
        )
        assert result.status == "ok"
        assert {c.metric_id for c in result.claims} == {f"points:{aggregation}"}
        observed[aggregation] = result.claims[0]
    assert observed["average"].value == pytest.approx(
        observed["total"].value / observed["average"].sample_size
    )


async def test_same_turn_execution_returns_canonical_committed_answer(local_redis):
    from app.services.analyst_sessions import SessionTurn

    first = await SessionTurn.begin(None, "same-turn-reconciled", 0, {"question": "stat"})
    await local_redis.delete(first.key + ":lease")
    second = await SessionTurn.begin(None, "same-turn-reconciled", 0, {"question": "stat"})
    assert await second.commit({"answer": "Canonical"}, {"intent": "canonical"})
    assert await first.commit({"answer": "Stale"}, {"intent": "stale"})
    assert first.replay == {"answer": "Canonical"}


@pytest.mark.parametrize(
    "question",
    [
        "How did Brunson perform in points and assists on January 1, 2026?",
        "What were Brunson's average points and assists on January 1, 2026?",
    ],
)
async def test_named_compound_stats_are_not_an_unqualified_profile(
    client, local_redis, monkeypatch, question
):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(get_settings(), "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        await make_tools(db)
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "turn_id": "named-compound-profile-case",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state_committed"]
    delivered = {
        c["metadata"]["claim"]["metric_id"]
        for c in body["citations"]
        if c.get("metadata", {}).get("claim")
    }
    assert delivered == {"points:average", "assists:average"}
