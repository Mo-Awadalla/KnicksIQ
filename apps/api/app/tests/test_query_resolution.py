"""Deterministic basketball query-resolution behavior."""

from __future__ import annotations

from app.models.game import Game
from app.models.player import Player
from app.services.query_resolution import resolve_query
from sqlalchemy import select


async def test_alias_and_safe_typo_resolve_to_canonical_player_ids(db_session):
    brunson = (
        await db_session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
    ).scalar_one()

    alias = await resolve_query(
        db_session,
        "What was JB's points average over the last 3 games?",
        intent="player_trend",
    )
    typo = await resolve_query(
        db_session,
        "How many points did Brunsn score?",
        intent="player_stat",
    )

    assert alias.player_ids == [brunson.id]
    assert alias.relative_game_count == 3
    assert alias.metric == "points"
    assert typo.player_ids == [brunson.id]
    assert typo.requires_clarification is False


async def test_relative_timeframes_use_the_active_archive_max_date(db_session):
    latest = (
        await db_session.execute(select(Game).order_by(Game.game_date.desc()).limit(1))
    ).scalar_one()

    resolved = await resolve_query(
        db_session,
        "What happened in the last game this month?",
        intent="narrative",
    )

    assert resolved.game_ids == [latest.id]
    assert resolved.date_start == latest.game_date.replace(day=1)
    assert resolved.date_end == latest.game_date
    assert resolved.relative_game_count == 1


async def test_contextual_splits_and_periods_become_typed_filters(db_session):
    resolved = await resolve_query(
        db_session,
        "How did the Knicks do in road wins in the second half of April?",
        intent="player_split",
    )

    assert resolved.home_away == "away"
    assert resolved.game_result == "W"
    assert resolved.periods == [3, 4]
    assert resolved.date_start is not None and resolved.date_start.month == 4
    assert resolved.date_end is not None and resolved.date_end.month == 4


async def test_superlative_game_reference_resolves_structurally(db_session):
    games = list((await db_session.execute(select(Game))).scalars())
    biggest_win = max(
        games,
        key=lambda game: (
            (game.home_score if game.home_team_id == "NYK" else game.away_score)
            - (game.away_score if game.home_team_id == "NYK" else game.home_score),
            game.game_date,
            game.id,
        ),
    )

    resolved = await resolve_query(
        db_session,
        "What did Towns do in the biggest win?",
        intent="narrative",
    )

    assert resolved.game_ids == [biggest_win.id]
    assert resolved.requires_clarification is False


async def test_descriptive_game_reference_resolves_through_structured_games(db_session):
    boston = (
        await db_session.execute(
            select(Game).where((Game.home_team_id == "BOS") | (Game.away_team_id == "BOS"))
        )
    ).scalar_one()

    resolved = await resolve_query(
        db_session,
        "What happened in the Boston game?",
        intent="narrative",
    )

    assert resolved.opponent_id == "BOS"
    assert resolved.team_ids == ["BOS"]
    assert resolved.game_ids == [boston.id]
    assert resolved.requires_clarification is False


async def test_common_word_was_does_not_resolve_to_washington(db_session):
    resolved = await resolve_query(
        db_session,
        "What was the Knicks average score per game?",
        intent="descriptive",
    )

    assert resolved.team_ids == []
    assert resolved.game_ids == []
    assert resolved.requires_clarification is False


async def test_full_name_consumes_surname_before_ambiguity_check(db_session):
    db_session.add(
        Player(
            nba_player_id=999_997,
            full_name="Miles Bridges",
            team_id="CHA",
            position="F",
            jersey_number="0",
        )
    )
    await db_session.flush()
    mikal = (
        await db_session.execute(select(Player).where(Player.full_name == "Mikal Bridges"))
    ).scalar_one()

    resolved = await resolve_query(
        db_session,
        "What was Mikal Bridges' three-point percentage?",
        intent="player_stat",
    )

    assert resolved.player_ids == [mikal.id]
    assert resolved.requires_clarification is False


async def test_ambiguous_surname_returns_clarification(db_session):
    db_session.add(
        Player(
            nba_player_id=999_999,
            full_name="Kevin Hart",
            team_id="NYK",
            position="G",
            jersey_number="99",
        )
    )
    await db_session.flush()

    resolved = await resolve_query(
        db_session,
        "How many points did Hart score?",
        intent="player_stat",
    )

    assert resolved.requires_clarification is True
    assert resolved.clarification_reason == "ambiguous_player"
    assert resolved.clarification_options == ["Josh Hart", "Kevin Hart"]


def test_resolved_filters_replace_model_invented_internal_ids():
    from app.api.analysis import _apply_resolved_filters
    from app.services.query_resolution import ResolvedQuery
    from app.services.retrieval_planner import RetrievalPlan, RetrievalPlanFilters

    resolved = ResolvedQuery(
        intent="narrative",
        player_ids=[11],
        team_ids=["BOS"],
        opponent_id="BOS",
        game_ids=[22],
        data_version="v1",
    )
    model_plan = RetrievalPlan(
        supported=True,
        intent="narrative",
        queries=["Boston"],
        collections=["reports"],
        filters=RetrievalPlanFilters(player_ids=[999], game_ids=[999]),
    )

    safe = _apply_resolved_filters(model_plan, resolved)

    assert safe.filters.player_ids == [11]
    assert safe.filters.game_ids == [22]
    assert safe.filters.team_ids == ["BOS"]
