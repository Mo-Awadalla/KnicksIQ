"""get_team_splits: failure cases first, then the bucket contract.

Every case runs through the real AnalystTools dispatch and claim pipeline against a
release-pinned archive. The tool must never invent a bucket, count a game twice or
divide by an empty denominator.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.models.box_score import PeriodScore
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall


async def _make_release(db, version: str = "splits-test") -> DatasetRelease:
    release = DatasetRelease(
        version=version,
        season="2025-26",
        source="test",
        manifest_sha256="b" * 64,
        validation_passed=True,
        status="staged",
    )
    db.add(release)
    await db.flush()
    return release


async def _game(
    db,
    release: DatasetRelease,
    *,
    game_date: date,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    season_type: str = "regular",
    periods: tuple[int, ...] = (),
) -> Game:
    identity = f"{release.version}-{game_date}-{home}-{away}"
    game = Game(
        release_id=release.id,
        nba_game_id=identity,
        season=release.season,
        game_date=game_date,
        home_team_id=home,
        away_team_id=away,
        home_score=home_score,
        away_score=away_score,
        status="final",
        season_type=season_type,
        source_name="test",
        source_game_id=identity,
    )
    db.add(game)
    await db.flush()
    for period in periods:
        db.add(
            PeriodScore(
                release_id=release.id,
                game_id=game.id,
                team_id="NYK",
                period=period,
                points=25,
            )
        )
    return game


async def _run(db, release: DatasetRelease, question: str):
    tools = AnalystTools(db, release, question, release.season, {})
    await tools.prepare()
    return await tools.execute(ToolCall(name="get_team_splits", question=question))


def _claim(result, metric_id: str):
    return next(claim for claim in result.claims if claim.metric_id == metric_id)


def _value(claim) -> dict[str, Any]:
    assert isinstance(claim.value, dict)
    return claim.value


async def _seed_home_road_and_boston(db, release):
    await _game(
        db,
        release,
        game_date=date(2026, 1, 1),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )
    await _game(
        db,
        release,
        game_date=date(2026, 1, 2),
        home="TOR",
        away="NYK",
        home_score=105,
        away_score=95,
    )
    await _game(
        db,
        release,
        game_date=date(2026, 1, 10),
        home="NYK",
        away="BOS",
        home_score=120,
        away_score=118,
    )
    await _game(
        db,
        release,
        game_date=date(2026, 1, 20),
        home="PHI",
        away="NYK",
        home_score=100,
        away_score=130,
    )
    await _game(
        db,
        release,
        game_date=date(2026, 4, 20),
        home="NYK",
        away="BOS",
        home_score=100,
        away_score=98,
        season_type="playoffs",
    )
    await _game(
        db,
        release,
        game_date=date(2026, 4, 22),
        home="BOS",
        away="NYK",
        home_score=110,
        away_score=90,
        season_type="playoffs",
    )


async def test_home_road_comparison_defaults_to_regular_season(db_session):
    release = await _make_release(db_session)
    await _seed_home_road_and_boston(db_session, release)

    result = await _run(db_session, release, "Compare the Knicks' offense at home and on the road.")

    assert result.status == "ok"
    home = _claim(result, "team_splits:home")
    away = _claim(result, "team_splits:away")
    assert home.value == {
        "games": 2,
        "wins": 2,
        "losses": 0,
        "points_for_per_game": 115.0,
        "points_against_per_game": 109.0,
        "margin_per_game": 6.0,
    }
    assert away.value == {
        "games": 2,
        "wins": 1,
        "losses": 1,
        "points_for_per_game": 112.5,
        "points_against_per_game": 102.5,
        "margin_per_game": 10.0,
    }
    assert home.season_type == "regular" and away.season_type == "regular"
    assert "regular season" in home.statement
    assert {claim.metric_id for claim in result.claims} == {
        "team_splits:home",
        "team_splits:away",
    }


async def test_opponent_buckets_include_phase_breakdown(db_session):
    release = await _make_release(db_session)
    await _seed_home_road_and_boston(db_session, release)

    result = await _run(db_session, release, "What was the Knicks record against Boston?")

    overall = _claim(result, "team_splits:opponent:BOS:all")
    regular = _claim(result, "team_splits:opponent:BOS:regular")
    playoffs = _claim(result, "team_splits:opponent:BOS:playoffs")
    assert overall.value == {
        "games": 4,
        "wins": 3,
        "losses": 1,
        "points_for_per_game": 105.0,
        "points_against_per_game": 106.5,
        "margin_per_game": -1.5,
    }
    assert overall.season_type is None
    assert _value(regular)["games"] == 2 and _value(regular)["wins"] == 2
    assert regular.season_type == "regular"
    assert _value(playoffs)["games"] == 2 and _value(playoffs)["wins"] == 1
    assert playoffs.season_type == "playoffs"


async def test_empty_playoff_bucket_returns_no_matching_results(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 1),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )

    result = await _run(db_session, release, "Compare their home and road record in the playoffs.")

    assert result.status == "no_matching_results"
    assert result.claims == []
    assert "not evidence" in result.message


async def test_neutral_site_is_declined_not_guessed(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 1),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )

    result = await _run(db_session, release, "How did the Knicks do at a neutral site?")

    assert result.status == "unsupported_metric_or_scope"
    assert result.claims == []
    assert "neutral" in result.message.lower()


async def test_overtime_games_are_counted_once(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 4),
        home="WAS",
        away="NYK",
        home_score=138,
        away_score=140,
        periods=(1, 2, 3, 4, 5, 6),
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 10),
        home="NYK",
        away="IND",
        home_score=134,
        away_score=137,
        periods=(1, 2, 3, 4, 5),
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 12),
        home="NYK",
        away="CHI",
        home_score=110,
        away_score=100,
    )

    result = await _run(db_session, release, "How did they do in overtime games?")

    overtime = _claim(result, "team_splits:overtime")
    assert overtime.value == {
        "games": 2,
        "wins": 1,
        "losses": 1,
        "points_for_per_game": 137.0,
        "points_against_per_game": 137.5,
        "margin_per_game": -0.5,
    }
    assert "once" in " ".join(overtime.coverage_limitations).lower()


async def test_tied_final_is_excluded_from_record(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 1),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 2),
        home="NYK",
        away="BOS",
        home_score=100,
        away_score=100,
    )

    result = await _run(db_session, release, "What was their record this season?")

    scope = _claim(result, "team_splits:scope")
    assert _value(scope)["games"] == 1 and _value(scope)["wins"] == 1
    assert "tie" in " ".join(scope.coverage_limitations).lower()


async def test_back_to_back_counts_only_the_second_game(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 3),
        home="NYK",
        away="ORL",
        home_score=100,
        away_score=90,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 4),
        home="WAS",
        away="NYK",
        home_score=138,
        away_score=140,
        periods=(1, 2, 3, 4, 5, 6),
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 5),
        home="NYK",
        away="CHA",
        home_score=100,
        away_score=101,
    )

    result = await _run(db_session, release, "How many back-to-backs did they win in February?")

    back_to_back = _claim(result, "team_splits:back_to_back")
    assert _value(back_to_back)["games"] == 2
    assert _value(back_to_back)["wins"] == 1
    assert "second game" in " ".join(back_to_back.coverage_limitations).lower()


async def test_month_comparison_builds_both_buckets(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 5),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 8),
        home="TOR",
        away="NYK",
        home_score=105,
        away_score=95,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 5),
        home="NYK",
        away="BOS",
        home_score=120,
        away_score=100,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 2, 8),
        home="NYK",
        away="PHI",
        home_score=110,
        away_score=105,
    )

    result = await _run(
        db_session, release, "Compare their January record with their February record."
    )

    january = _claim(result, "team_splits:month:2026-01")
    february = _claim(result, "team_splits:month:2026-02")
    assert _value(january)["games"] == 2 and _value(january)["wins"] == 1
    assert _value(february)["games"] == 2 and _value(february)["wins"] == 2
    assert {claim.metric_id for claim in result.claims} == {
        "team_splits:month:2026-01",
        "team_splits:month:2026-02",
    }


async def test_all_star_break_is_inferred_from_schedule_gap(db_session):
    release = await _make_release(db_session)
    dates = [
        date(2026, 1, 15),
        date(2026, 1, 18),
        date(2026, 1, 22),
        date(2026, 1, 26),
        date(2026, 1, 30),
        date(2026, 2, 3),
        date(2026, 2, 7),
        date(2026, 2, 11),
        date(2026, 2, 20),
        date(2026, 2, 24),
        date(2026, 2, 28),
        date(2026, 3, 4),
        date(2026, 3, 8),
    ]
    for index, game_date in enumerate(dates):
        await _game(
            db_session,
            release,
            game_date=game_date,
            home="NYK",
            away="BOS",
            home_score=110 if index % 2 == 0 else 100,
            away_score=100 if index % 2 == 0 else 110,
        )

    after = await _run(db_session, release, "What was their record after the All-Star break?")
    after_bucket = _claim(after, "team_splits:after_break")
    assert _value(after_bucket)["games"] == 5

    before = await _run(db_session, release, "What was their record before the All-Star break?")
    before_bucket = _claim(before, "team_splits:before_break")
    assert _value(before_bucket)["games"] == 8


async def test_first_and_last_windows_use_the_phase_population(db_session):
    release = await _make_release(db_session)
    for index in range(12):
        await _game(
            db_session,
            release,
            game_date=date(2026, 1, 1 + index),
            home="NYK",
            away="BOS",
            home_score=110 if index % 2 == 0 else 100,
            away_score=100 if index % 2 == 0 else 110,
        )

    result = await _run(db_session, release, "Compare their first 5 games with their last 5 games.")

    first = _claim(result, "team_splits:window:first:5")
    last = _claim(result, "team_splits:window:last:5")
    assert _value(first)["games"] == 5 and _value(last)["games"] == 5
    assert _value(first)["wins"] == 3 and _value(last)["wins"] == 2


async def test_conference_buckets_use_the_teams_table(db_session):
    release = await _make_release(db_session)
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 1),
        home="NYK",
        away="BOS",
        home_score=110,
        away_score=100,
    )
    await _game(
        db_session,
        release,
        game_date=date(2026, 1, 5),
        home="NYK",
        away="LAL",
        home_score=100,
        away_score=110,
    )

    result = await _run(
        db_session, release, "Did the Knicks fare better against Eastern or Western teams?"
    )

    east = _claim(result, "team_splits:conference:East")
    west = _claim(result, "team_splits:conference:West")
    assert _value(east)["games"] == 1 and _value(east)["wins"] == 1
    assert _value(west)["games"] == 1 and _value(west)["wins"] == 0


async def test_close_middle_and_blowout_buckets_do_not_overlap(db_session):
    release = await _make_release(db_session)
    for index, margin in enumerate((2, 5, 7, 10, 20)):
        await _game(
            db_session,
            release,
            game_date=date(2026, 1, 1 + index),
            home="NYK",
            away="BOS",
            home_score=100 + margin,
            away_score=100,
        )

    result = await _run(db_session, release, "Compare close games with blowouts.")

    close = _claim(result, "team_splits:close")
    middle = _claim(result, "team_splits:middle")
    blowout = _claim(result, "team_splits:blowout")
    assert _value(close)["games"] == 2
    assert _value(middle)["games"] == 1
    assert _value(blowout)["games"] == 2
    assert _value(close)["games"] + _value(middle)["games"] + _value(blowout)["games"] == 5
