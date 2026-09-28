"""Permanent, isolated reproductions from knicksiq_diagnose.py; no provider calls."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from app.core.config import get_settings
from app.models.game import Game
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.test_player_intelligence import _seed_release_stats
from sqlalchemy import select


async def seed_record(db):
    release, _ = await _seed_release_stats(db)
    games = list(
        (
            await db.execute(select(Game).where(Game.release_id == release.id).order_by(Game.id))
        ).scalars()
    )
    games[-1].home_score = 90
    await db.commit()
    return release


async def record_tools(db, release, question, state=None):
    tools = AnalystTools(db, release, question, release.season, state or {})
    await tools.prepare()
    return tools


@pytest.mark.parametrize("phrase", ["wins and losses", "record", "win-loss record", "W–L record"])
@pytest.mark.parametrize(
    "scope",
    [
        "",
        "against Boston",
        "at home",
        "in the regular season",
        "from 2026-01-01 through 2026-01-03",
    ],
)
async def test_record_population(db_session, phrase, scope):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, f"What were their {phrase} {scope}?")
    result = await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    values = {c.metric_id: c.value for c in result.claims}
    assert tools.scope.game_result is None
    assert (values["wins"], values["losses"]) == (2, 1)
    assert values["wins"] + values["losses"] == result.claims[0].sample_size == 3


@pytest.mark.parametrize(
    "question,result,expected",
    [
        ("show only wins", "W", (2, 0)),
        ("in losses", "L", (0, 1)),
        ("Brunson's stats in wins", "W", (2, 0)),
    ],
)
async def test_explicit_result_subset(db_session, question, result, expected):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, question)
    assert tools.scope.game_result == result
    facts = await tools.execute(ToolCall(name="get_team_stats", question=question))
    values = {c.metric_id: c.value for c in facts.claims}
    assert (values["wins"], values["losses"]) == expected


async def test_record_followup_clears_only_result(db_session):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "show only home wins against Boston")
    tools = await record_tools(
        db_session, release, "And what was their overall record?", tools.state
    )
    assert tools.scope.game_result is None
    assert tools.scope.home_away == "home"
    assert tools.scope.opponent_id == "BOS"


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, TimeoutError])
async def test_early_failure_recovers_facts(db_session, monkeypatch, failure):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    loop = AnalystLoop(tools, [])
    monkeypatch.setattr(loop, "reserve", AsyncMock(return_value=True))
    monkeypatch.setattr(loop, "investigate", AsyncMock(side_effect=failure("controlled")))
    result = await loop.run()
    assert "wins: 2" in result["answer"] and "losses: 1" in result["answer"]
    assert result["citations"] and result["degraded"]
    assert result["route"] == "factual_fallback" and not result["llm_validated"]


async def test_retrieval_failure_returns_unavailable_once(db_session, monkeypatch):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    retrieve = AsyncMock(side_effect=RuntimeError("controlled"))
    monkeypatch.setattr(tools, "execute", retrieve)
    result = await AnalystLoop(tools, []).run(allow_model=False)
    assert "unavailable" in result["answer"].lower()
    assert not result["citations"] and result["degraded"]
    assert retrieve.await_count == 1


async def test_api_record_and_failure(client, monkeypatch):
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await seed_record(db)
    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(AnalystLoop, "reserve", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AnalystLoop, "investigate", AsyncMock(side_effect=RuntimeError("controlled"))
    )
    for question in ["What were their wins and losses?", "What was their record?"]:
        response = await client.post("/analysis/query", json={"question": question})
        assert response.status_code == 200
        result = response.json()
        assert "wins: 2" in result["answer"] and "losses: 1" in result["answer"]
        assert result["citations"] and result["degraded"]


async def test_recovery_timeout_and_cancellation(db_session, monkeypatch):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    monkeypatch.setattr(get_settings(), "analyst_deadline_seconds", 0.7)

    async def slow(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(tools, "execute", slow)
    started = time.monotonic()
    result = await AnalystLoop(tools, []).run(allow_model=False)
    assert time.monotonic() - started < 0.6
    assert "unavailable" in result["answer"].lower() and not result["citations"]
    monkeypatch.setattr(tools, "execute", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await AnalystLoop(tools, []).run(allow_model=False)


async def test_current_evidence_reused_and_prior_facts_not_reused(db_session, monkeypatch):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    facts = await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    loop = AnalystLoop(tools, [])
    loop.results.append(facts)
    retrieve = AsyncMock(wraps=tools.execute)
    monkeypatch.setattr(tools, "execute", retrieve)
    monkeypatch.setattr(loop, "reserve", AsyncMock(return_value=True))
    monkeypatch.setattr(loop, "investigate", AsyncMock(side_effect=RuntimeError("review failure")))
    result = await loop.run()
    assert result["citations"] and retrieve.await_count == 0
    # A populated claims dictionary alone must not suppress current-question retrieval.
    new_loop = AnalystLoop(tools, [])
    result = await new_loop.run(allow_model=False)
    assert result["citations"] and retrieve.await_count == 1


async def test_budget_denial_and_exhausted_deadline(db_session, monkeypatch):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    loop = AnalystLoop(tools, [])
    monkeypatch.setattr(loop, "reserve", AsyncMock(return_value=False))
    model = AsyncMock(side_effect=AssertionError("must not call provider"))
    monkeypatch.setattr(loop, "model", model)
    assert (await loop.run())["citations"]
    assert model.await_count == 0
    loop = AnalystLoop(tools, [], started=time.monotonic() - 1000)
    retrieve = AsyncMock(side_effect=AssertionError("deadline exhausted"))
    monkeypatch.setattr(tools, "execute", retrieve)
    result = await loop.run(allow_model=False)
    assert not result["citations"] and "unavailable" in result["answer"].lower()
    assert retrieve.await_count == 0
