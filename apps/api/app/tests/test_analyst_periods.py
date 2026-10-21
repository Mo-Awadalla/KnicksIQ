"""Failure cases for get_period_scoring, written before the handler.

Each test is a way the tool could lie or crash: missing rows read as zero, overtime folded
into the fourth quarter or second half, halves taken from the final score, ties counted as
wins, a season-level default that mixes playoffs into the regular season, or the periods
guard refusing a supported tool.
"""

from __future__ import annotations

from datetime import date

from app.models.box_score import PeriodScore
from app.models.game import Game
from app.services.analyst_tool_periods import run as period_run
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import delete, select


async def _seed(db, question: str):
    release, _ = await _seed_release_stats(db)
    games = list(
        (
            await db.execute(select(Game).where(Game.release_id == release.id).order_by(Game.id))
        ).scalars()
    )
    tools = AnalystTools(db, release, question, release.season, {})
    await tools.prepare()
    return tools, games


async def _add_periods(db, release, game, home, away, skip=()):
    """home/away are four quarter scores; period 5+ rows are appended past four."""
    for team_id, scores in ((game.home_team_id, home), (game.away_team_id, away)):
        for index, points in enumerate(scores, start=1):
            if index in skip:
                continue
            db.add(
                PeriodScore(
                    release_id=release.id,
                    game_id=game.id,
                    team_id=team_id,
                    period=index,
                    points=points,
                )
            )


async def _call(tools, games, question=None, scope=None):
    question = question or tools.question
    result = await period_run(
        tools,
        ToolCall(name="get_period_scoring", question=question),
        scope or tools.scope,
        games,
    )
    return result


def _claim(result, metric: str):
    return next(claim for claim in result.claims if claim.metric_id == metric)


def _text(result) -> str:
    value = _claim(result, "period_report").value
    assert isinstance(value, str)
    return value


async def test_missing_period_rows_are_coverage_gaps_not_zeros(db_session):
    tools, games = await _seed(db_session, "Compare the Knicks' third-quarter scoring.")
    assert tools.scope is not None
    await _add_periods(db_session, tools.release, games[0], [28, 28, 28, 27], [25, 25, 25, 25])
    await _add_periods(db_session, tools.release, games[1], [30, 30, 30, 22], [25, 25, 25, 25])
    await db_session.commit()

    result = await _call(tools, games)

    assert result.status == "incomplete_coverage"
    text = _text(result)
    assert "2 of 3 games" in text
    assert "1 coverage gaps" in text
    assert f"game {games[2].id}" in text or "1 coverage gaps" in text
    assert "reg Q3: 58 pts (29.0/g)" in text
    assert "diff +8, 2-0-0" in text


async def test_partial_team_rows_are_excluded_not_zero(db_session):
    tools, games = await _seed(db_session, "Describe the Knicks' third quarter.")
    assert tools.scope is not None
    layouts = (
        ([28, 28, 28, 27], [25, 25, 25, 25]),
        ([30, 30, 30, 22], [25, 25, 25, 25]),
        ([28, 28, 28, 29], [25, 25, 25, 25]),
    )
    for game, (home, away) in zip(games, layouts, strict=True):
        await _add_periods(db_session, tools.release, game, home, away)
    # The away team's fourth quarter is absent; the game cannot be used at all.
    await db_session.commit()
    await db_session.execute(
        delete(PeriodScore).where(
            PeriodScore.game_id == games[2].id,
            PeriodScore.team_id == games[2].away_team_id,
            PeriodScore.period == 4,
        )
    )
    await db_session.commit()

    result = await _call(tools, games)

    assert result.status == "incomplete_coverage"
    text = _text(result)
    assert "2 of 3 games" in text
    assert "reg Q3: 58 pts" in text


async def test_overtime_periods_are_separate_from_q4_and_halves(db_session):
    tools, games = await _seed(db_session, "How did the Knicks do in overtime?")
    assert tools.scope is not None
    games[0].home_score = 120
    games[0].away_score = 118
    await _add_periods(
        db_session,
        tools.release,
        games[0],
        [25, 25, 25, 25, 20],
        [25, 25, 25, 25, 18],
    )
    await db_session.commit()

    result = await _call(
        tools,
        [games[0]],
        scope=tools.scope.model_copy(update={"periods": [1, 2, 3, 4, 5]}),
    )

    text = _text(result)
    assert "reg Q4: 25 pts" in text
    assert "reg OT: 20 pts" in text
    assert "Q4 25-25 (+0) OT 20-18 (+2)" in text
    assert "; 120-118 W (+2)" in text


async def test_halves_are_summed_from_quarters_not_final_score(db_session):
    tools, games = await _seed(db_session, "What changed after halftime?")
    assert tools.scope is not None
    await _add_periods(db_session, tools.release, games[0], [20, 30, 35, 26], [20, 20, 30, 30])
    await db_session.commit()

    result = await _call(tools, [games[0]])

    text = _text(result)
    assert "half 50-40, 2H 61-60" in text
    assert "; 111-100 W" in text
    assert "led 1, trailed 0; comebacks 0, blown 0" in text


async def test_tied_quarter_is_not_a_win(db_session):
    tools, games = await _seed(db_session, "How often did the Knicks win the first quarter?")
    assert tools.scope is not None
    layouts = (
        ([25, 28, 30, 28], [25, 25, 25, 25]),
        ([25, 30, 30, 27], [25, 25, 25, 25]),
        ([25, 28, 30, 30], [25, 25, 25, 25]),
    )
    for game, (home, away) in zip(games, layouts, strict=True):
        await _add_periods(db_session, tools.release, game, home, away)
    await db_session.commit()

    result = await _call(tools, games, scope=tools.scope.model_copy(update={"periods": [1, 3]}))

    text = _text(result)
    assert "reg Q1: 75 pts (25.0/g)" in text
    assert "diff +0, 0-3-0" in text
    assert "reg Q3: 90 pts (30.0/g)" in text
    assert "diff +15, 3-0-0" in text


async def test_season_level_defaults_to_regular_season(db_session):
    tools, games = await _seed(db_session, "Describe the Knicks' worst third quarter.")
    assert tools.scope is not None
    layouts = (
        ([28, 28, 28, 27], [25, 25, 25, 25]),
        ([30, 30, 30, 22], [25, 25, 25, 25]),
        ([28, 28, 28, 29], [25, 25, 25, 25]),
    )
    for game, (home, away) in zip(games, layouts, strict=True):
        await _add_periods(db_session, tools.release, game, home, away)
    playoff = Game(
        release_id=tools.release.id,
        nba_game_id="periods-playoff",
        season=tools.release.season,
        game_date=date(2026, 4, 20),
        home_team_id="NYK",
        away_team_id="BOS",
        home_score=100,
        away_score=90,
        status="final",
        season_type="playoffs",
        source_name="test",
        source_game_id="periods-playoff",
    )
    db_session.add(playoff)
    await db_session.flush()
    await _add_periods(db_session, tools.release, playoff, [40, 20, 20, 20], [25, 25, 20, 20])
    await db_session.commit()

    result = await _call(tools, games + [playoff])

    text = _text(result)
    assert "playoffs" not in text
    assert "reg Q3: 86 pts" in text
    assert "diff +11, 3-0-0" in text


async def test_opponent_question_breaks_out_regular_and_playoffs(db_session):
    tools, games = await _seed(db_session, "Walk me through the fourth quarter against Boston.")
    assert tools.scope is not None
    layouts = (
        ([28, 28, 28, 27], [25, 25, 25, 25]),
        ([30, 30, 30, 22], [25, 25, 25, 25]),
        ([28, 28, 28, 29], [25, 25, 25, 25]),
    )
    for game, (home, away) in zip(games, layouts, strict=True):
        await _add_periods(db_session, tools.release, game, home, away)
    playoff = Game(
        release_id=tools.release.id,
        nba_game_id="periods-playoff",
        season=tools.release.season,
        game_date=date(2026, 4, 20),
        home_team_id="NYK",
        away_team_id="BOS",
        home_score=100,
        away_score=90,
        status="final",
        season_type="playoffs",
        source_name="test",
        source_game_id="periods-playoff",
    )
    db_session.add(playoff)
    await db_session.flush()
    await _add_periods(db_session, tools.release, playoff, [40, 20, 20, 20], [25, 25, 20, 20])
    await db_session.commit()

    result = await _call(tools, games + [playoff])

    text = _text(result)
    assert "Phases: 3 reg, 1 playoffs" in text
    assert "4 of 4 games" in text
    assert "h p: Q4 20-20 (+0)" in text
    assert "04-20" in text


async def test_halftime_comeback_and_blown_lead_are_counted(db_session):
    tools, games = await _seed(db_session, "What changed after halftime?")
    assert tools.scope is not None
    await _add_periods(db_session, tools.release, games[0], [20, 25, 33, 33], [27, 28, 22, 23])
    games[1].home_score = 100
    games[1].away_score = 105
    await _add_periods(db_session, tools.release, games[1], [30, 30, 20, 20], [25, 25, 28, 27])
    await _add_periods(db_session, tools.release, games[2], [28, 28, 28, 29], [25, 25, 25, 25])
    await db_session.commit()

    result = await _call(tools, games)

    text = _text(result)
    assert "comebacks 1, blown 1" in text
    assert "largest comeback 10 vs" in text
    assert "largest lead lost 10 vs" in text


async def test_supported_tool_passes_the_periods_guard_but_others_still_refuse(db_session):
    tools, _ = await _seed(
        db_session, "Compare the Knicks' third-quarter and fourth-quarter scoring."
    )
    assert tools.scope is not None
    allowed = await tools.execute(ToolCall(name="get_period_scoring", question=tools.question))
    refused = await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    assert allowed.status != "unsupported_metric_or_scope"
    assert refused.status == "unsupported_metric_or_scope"
    assert "full-game" in refused.message


async def test_no_games_returns_no_matching_results(db_session):
    tools, _ = await _seed(db_session, "Describe the Knicks' third quarter against Denver.")
    assert tools.scope is not None
    result = await tools.execute(ToolCall(name="get_period_scoring", question=tools.question))
    assert result.status == "no_matching_results"
