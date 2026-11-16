"""Permanent, isolated reproductions from knicksiq_diagnose.py; no provider calls."""

from unittest.mock import AsyncMock

import pytest
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.support.analyst_protocol import local_redis  # noqa: F401
from app.tests.support.factual_queries import lookup, text
from app.tests.support.player_archive import _seed_release_stats
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


@pytest.mark.parametrize(
    "phrase,scope",
    [
        ("wins and losses", ""),
        ("record", "against Boston"),
        ("win-loss record", "at home"),
        ("W–L record", "in the regular season"),
        ("record", "from 2026-01-01 through 2026-01-03"),
    ],
)
async def test_record_population(db_session, phrase, scope):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, f"What were their {phrase} {scope}?")
    result = await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    values = {c.metric_id: c.value for c in result.claims}
    assert tools.scope is not None
    assert tools.scope.game_result is None
    assert (values["wins"], values["losses"]) == (2, 1)
    assert isinstance(values["wins"], int) and isinstance(values["losses"], int)
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
    assert tools.scope is not None
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
    assert tools.scope is not None
    assert tools.scope.game_result is None
    assert tools.scope.home_away == "home"
    assert tools.scope.opponent_id == "BOS"


def test_regular_season_is_not_a_fuzzy_player_name():
    from app.models.player import Player
    from app.services.query_players import resolve_player_mentions

    player = Player(id=314, full_name="Tari Eason", team_id="HOU", nba_player_id=314)
    resolved, _ = resolve_player_mentions(
        "What was the Knicks record in the 2025-26 regular season?",
        [player],
        typo_threshold=0.86,
    )
    assert resolved == []


async def test_record_excludes_undecided_games(db_session):
    release = await seed_record(db_session)
    games = list(
        (
            await db_session.execute(
                select(Game).where(Game.release_id == release.id).order_by(Game.id)
            )
        ).scalars()
    )
    games[0].status = "scheduled"
    games[1].home_score = games[1].away_score
    await db_session.commit()
    tools = await record_tools(db_session, release, "What was their record?")
    result = await lookup(tools)
    assert "wins: 0" in text(result) and "losses: 1" in text(result)
    assert result.claims


@pytest.mark.parametrize(
    "question",
    [
        "What was their record in the 2024-25 season?",
        "What was their record in the first quarter?",
    ],
)
async def test_prior_record_cannot_answer_unsupported_current_scope(db_session, question):
    release = await seed_record(db_session)
    tools = await record_tools(db_session, release, "What was their record?")
    await lookup(tools)
    current = await record_tools(db_session, release, question, tools.state)
    result = await lookup(current)
    assert not result.claims
    assert "wins: 2" not in text(result)


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Will the Knicks win their next game?", "refuse"),
        ("How will Brunson play next season?", "refuse"),
        ("Who was better?", "clarify"),
        ("Will he win that game tomorrow?", "refuse"),
        ("Who will win in 2028?", "refuse"),
        ("How many points did Will Richard score in this archive?", "answer"),
    ],
)
async def test_fallback_capability_precedes_name_and_comparison_ambiguity(
    db_session, question, expected
):
    """Modal names, future dates and unanchored pronouns cannot override refusal.

    A vague comparison must not return unrelated team totals. A real full player
    name must remain answerable instead of losing the name to a word blacklist.
    """
    release = await seed_record(db_session)
    game = (
        await db_session.execute(
            select(Game).where(Game.release_id == release.id).order_by(Game.id).limit(1)
        )
    ).scalar_one()
    players = [
        Player(nba_player_id=999_990 + index, full_name=name, team_id="NYK")
        for index, name in enumerate(("Will Richard", "Will Riley"))
    ]
    db_session.add_all(players)
    await db_session.flush()
    db_session.add_all(
        [
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                minutes=1,
            )
            for player in players
        ]
    )
    await db_session.commit()
    tools = await record_tools(db_session, release, question)
    result = await lookup(tools)
    assert result.status in (
        {"ok", "incomplete_coverage"}
        if expected == "answer"
        else {"ambiguous_entity"}
        if expected == "clarify"
        else {"unsupported_metric_or_scope"}
    )
    if expected == "answer":
        assert {item.subject_id for item in result.claims} == {f"player:{players[0].id}"}
    else:
        assert result.claims == []


async def test_private_retrieval_failure_is_unavailable(client, monkeypatch):
    from app.conversation.facts import FactDesk
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await seed_record(db)
    monkeypatch.setattr(AnalystTools, "execute", AsyncMock(side_effect=RuntimeError("controlled")))
    desk = FactDesk("2025-26", {}, 6000, "lookup-failure")
    try:
        result = await desk.lookup("What was their record?")
        assert result["status"] == "unavailable"
        assert "facts" not in result
        assert "controlled" not in result["message"]
    finally:
        await desk.close()
