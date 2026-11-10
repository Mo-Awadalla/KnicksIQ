"""Deterministic basketball query-resolution behavior."""

from __future__ import annotations

from app.models.box_score import PlayerGameStat
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


async def test_full_name_consumes_surname_before_ambiguity_check(client, monkeypatch):
    from app.core.db import AsyncSessionLocal
    from app.tests.support.analytics_workflows import ask, claims, comparison_archive

    version, ids = await comparison_archive(monkeypatch)
    async with AsyncSessionLocal() as db:
        competitor = Player(nba_player_id=999_997, full_name="Miles Bridges", team_id="TOR")
        db.add(competitor)
        await db.flush()
        game = await db.get(Game, ids["2025-11-10"])
        assert game is not None
        db.add(
            PlayerGameStat(
                release_id=game.release_id,
                game_id=game.id,
                player_id=competitor.id,
                team_id="TOR",
                minutes=30,
                points=25,
            )
        )
        await db.commit()
    result = await ask(client, "What was Mikal Bridges' scoring average?", version)
    claim = claims(result)["points:average"]
    assert claim["value"] == 12
    assert "Mikal Bridges" in result["answer"]
    assert claim["release_id"] == version


async def test_ambiguous_surname_returns_clarification(client, monkeypatch):
    from app.core.db import AsyncSessionLocal
    from app.tests.support.analytics_workflows import ask, claims, comparison_archive

    version, ids = await comparison_archive(monkeypatch)
    async with AsyncSessionLocal() as db:
        competitor = Player(nba_player_id=999_999, full_name="Kevin Hart", team_id="NYK")
        db.add(competitor)
        await db.flush()
        josh = (
            await db.execute(select(Player).where(Player.full_name == "Josh Hart"))
        ).scalar_one()
        game = await db.get(Game, ids["2025-11-01"])
        assert game is not None
        db.add_all(
            [
                PlayerGameStat(
                    release_id=game.release_id,
                    game_id=game.id,
                    player_id=player.id,
                    team_id="NYK",
                    minutes=30,
                    points=10,
                )
                for player in (josh, competitor)
            ]
        )
        await db.commit()
    result = await ask(client, "How many points did Hart score?", version)
    assert result["outcome"] == "clarify"
    assert not claims(result)
    assert "Josh Hart" in result["answer"] and "Kevin Hart" in result["answer"]


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


async def test_explicit_rebounding_comparison_is_not_an_undefined_quality_judgment(db_session):
    players = list(
        (
            await db_session.execute(
                select(Player).where(Player.full_name.in_(["Karl-Anthony Towns", "Josh Hart"]))
            )
        ).scalars()
    )
    resolved = await resolve_query(
        db_session,
        "Who had the better rebounding season, Towns or Hart?",
        intent="player_comparison",
    )
    assert resolved.requires_clarification is False
    assert resolved.metric == "rebounds"
    assert set(resolved.player_ids) == {player.id for player in players}


async def test_single_initial_does_not_turn_an_article_into_a_player_filter(db_session):
    player = Player(nba_player_id=999_993, full_name="A.J. Lawson", team_id="NYK")
    db_session.add(player)
    await db_session.flush()
    search = await resolve_query(
        db_session,
        "Search the archive for the Knicks game against Cleveland on 2025-10-22. Cite a report.",
        intent="analyst",
    )
    named = await resolve_query(db_session, "What did A.J. Lawson score?", intent="player_stat")
    assert search.player_ids == []
    assert named.player_ids == [player.id]
