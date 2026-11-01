"""Player aggregate, comparison, leaderboard and presentation contracts."""

from __future__ import annotations

from datetime import date

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.player_analytics import answer_player_question
from app.services.player_intelligence.planning import _parse_plan
from app.services.player_intelligence.presentation import _answer_text
from app.tests.support.player_archive import _seed_release_stats
from basketball_core.analytics import AnalyticsOperation
from sqlalchemy import select


async def test_totals_averages_percentages_ratios_and_triple_doubles(db_session) -> None:
    await _seed_release_stats(db_session)
    total = await answer_player_question(
        db_session,
        question="How many points did JB score this season?",
        season="2025-26",
    )
    assert total is not None
    total_result = total.analytics["results"][0]
    assert total.analytics["plan"]["aggregation_mode"] == "total"
    assert total_result["raw_values"]["points"] == 50

    average = await answer_player_question(
        db_session,
        question="What did JB average per game in points this season?",
        season="2025-26",
    )
    assert average is not None
    assert average.analytics["results"][0]["raw_values"]["points"] == 25

    plan = _parse_plan(
        "KAT three point percentage and assist-to-turnover ratio plus triple-doubles",
        [],
    )
    assert {
        "three_point_percentage",
        "assist_turnover_ratio",
        "triple_doubles",
    }.issubset(plan.stats)


async def test_association_operation_precedes_outcome_filters_and_parses_plus(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="Did JB scoring 30 plus points cause the Knicks to win?",
        season="2025-26",
    )
    assert answer is not None
    plan = answer.analytics["plan"]
    assert plan["operations"] == [AnalyticsOperation.OUTCOME_ASSOCIATION.value]
    assert "outcome" not in plan["filters"]
    result = answer.analytics["results"][0]
    assert result["threshold"] == 30
    assert any("not causation" in warning for warning in result["warnings"])


async def test_default_leaderboard_is_knicks_only_and_false_team_premise_is_limited(
    db_session,
) -> None:
    release, _ = await _seed_release_stats(db_session)
    game = (await db_session.execute(select(Game).order_by(Game.id).limit(1))).scalar_one()
    opponent = Player(
        nba_player_id=999001,
        full_name="Kevin Durant",
        team_id="BOS",
        position="F",
        jersey_number="7",
    )
    db_session.add(opponent)
    await db_session.flush()
    db_session.add(
        PlayerGameStat(
            release_id=release.id,
            game_id=game.id,
            player_id=opponent.id,
            team_id="BOS",
            minutes=40,
            points=60,
            field_goals_attempted=25,
        )
    )
    await db_session.commit()

    leaders = await answer_player_question(
        db_session,
        question="Who led players in points this season?",
        season="2025-26",
    )
    assert leaders is not None
    entries = leaders.analytics["results"][0]["entries"]
    assert {entry["player_name"] for entry in entries} <= {
        "Jalen Brunson",
        "Karl-Anthony Towns",
    }

    false_premise = await answer_player_question(
        db_session,
        question="What did Knicks player Kevin Durant average in points?",
        season="2025-26",
    )
    assert false_premise is not None
    assert false_premise.analytics["status"] == "limited"
    assert false_premise.analytics["results"] == []


async def test_hardest_opposing_player_ranks_cumulative_plus_minus(db_session) -> None:
    release, _ = await _seed_release_stats(db_session)
    games = list(
        (
            await db_session.execute(
                select(Game).where(Game.release_id == release.id).order_by(Game.game_date)
            )
        ).scalars()
    )
    tatum = Player(
        nba_player_id=999101,
        full_name="Jayson Tatum",
        team_id="BOS",
        position="F",
        jersey_number="0",
    )
    brown = Player(
        nba_player_id=999102,
        full_name="Jaylen Brown",
        team_id="BOS",
        position="F",
        jersey_number="7",
    )
    db_session.add_all([tatum, brown])
    await db_session.flush()
    for game, tatum_plus_minus, brown_plus_minus in zip(
        games,
        (None, 12, 5),
        (15, 1, -4),
        strict=True,
    ):
        stats = [
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=brown.id,
                team_id="BOS",
                minutes=36,
                plus_minus=brown_plus_minus,
            )
        ]
        if tatum_plus_minus is not None:
            stats.append(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=tatum.id,
                    team_id="BOS",
                    minutes=38,
                    plus_minus=tatum_plus_minus,
                )
            )
        db_session.add_all(stats)
    await db_session.commit()

    answer = await answer_player_question(
        db_session,
        question=(
            "Which player gave the Knicks the hardest time when he was on the court all season?"
        ),
        season="2025-26",
    )

    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["entries"][0]["player_name"] == "Jayson Tatum"
    assert result["entries"][0]["raw_values"]["plus_minus"] == 17
    assert result["entries"][0]["sample_size"] == 2
    assert {citation["game_id"] for citation in answer.citations} == set(
        result["entries"][0]["source_game_ids"]
    )
    assert "cumulative plus-minus" in answer.answer.lower()

    explicit = await answer_player_question(
        db_session,
        question="Which opposing player had the most cumulative +/- against the Knicks?",
        season="2025-26",
    )

    assert explicit is not None
    explicit_leader = explicit.analytics["results"][0]["entries"][0]
    assert explicit_leader["player_name"] == "Jayson Tatum"
    assert explicit_leader["raw_values"]["plus_minus"] == 17


async def test_leader_totals_and_explicit_average_rank_different_players(db_session):
    await _seed_release_stats(db_session)
    total = await answer_player_question(
        db_session, question="Who led the Knicks in points?", season="2025-26"
    )
    assert total is not None
    average = await answer_player_question(
        db_session, question="Who led the Knicks in average points?", season="2025-26"
    )
    assert average is not None
    top = total.analytics["results"][0]["entries"][0]
    assert top["player_name"] == "Karl-Anthony Towns"
    assert top["raw_values"]["points"] == 51
    assert total.analytics["plan"]["aggregation_mode"] == "total"
    assert average.analytics["results"][0]["entries"][0]["player_name"] == "Jalen Brunson"
    assert average.analytics["results"][0]["entries"][0]["raw_values"]["points"] == 25


async def test_starts_returns_count_instead_of_scoring_average(db_session):
    release, player = await _seed_release_stats(db_session)
    rows = (
        (
            await db_session.execute(
                select(PlayerGameStat).where(
                    PlayerGameStat.release_id == release.id, PlayerGameStat.player_id == player.id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.starter = True
    await db_session.commit()
    answer = await answer_player_question(
        db_session, question="How many games did Jalen Brunson start?", season="2025-26"
    )
    assert answer is not None
    assert answer.analytics["plan"]["stats"] == ["starts"]
    assert answer.analytics["results"][0]["raw_values"] == {"starts": 2}
    assert "games started 2 total" in answer.answer


async def test_player_period_comparisons_keep_both_sides_and_full_season_baseline(db_session):
    release, _ = await _seed_release_stats(db_session)
    last = (
        await db_session.execute(
            select(Game).where(Game.release_id == release.id, Game.nba_game_id == "analytics-3")
        )
    ).scalar_one()
    last.game_date = date(2026, 2, 20)
    await db_session.commit()
    compare = await answer_player_question(
        db_session,
        question="Compare Brunson's last 1 game with his season average",
        season="2025-26",
    )
    assert compare is not None
    groups = compare.analytics["results"][0]["groups"]
    assert groups[0]["raw_values"]["points"] == 30
    assert groups[1]["raw_values"]["points"] == 25
    assert groups[1]["sample_size"] == 2
    split = await answer_player_question(
        db_session,
        question="Compare Brunson scoring before and after the All-Star break",
        season="2025-26",
    )
    assert split is not None
    groups = split.analytics["results"][0]["groups"]
    assert [r["raw_values"]["points"] for r in groups] == [20, 30]


async def test_biggest_win_selects_canonical_game_before_player_aggregation(db_session):
    release, _ = await _seed_release_stats(db_session)
    games = list(
        (
            await db_session.execute(
                select(Game).where(Game.release_id == release.id).order_by(Game.id)
            )
        ).scalars()
    )
    games[0].home_score = 150
    games[0].away_team_id = "TOR"
    await db_session.commit()
    answer = await answer_player_question(
        db_session, question="What did Towns do in the biggest win?", season="2025-26"
    )
    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["raw_values"] == {"points": 16, "rebounds": 10, "assists": 3}
    assert result["source_game_ids"] == [games[0].id]
    assert "2026-01-01 NYK 150-100 TOR" in answer.answer
    boston = await answer_player_question(
        db_session, question="What did Towns do in the biggest win against BOS?", season="2025-26"
    )
    assert boston is not None
    assert boston.analytics["results"][0]["raw_values"]["points"] == 18
    assert boston.analytics["results"][0]["source_game_ids"] == [games[2].id]


async def test_shooting_percentage_answer_does_not_claim_per_appearance(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="What was JB's field goal percentage this season?",
        season="2025-26",
    )
    assert answer is not None
    assert "field goal percentage" in answer.answer.lower()
    assert "per appearance" not in answer.answer
    assert "total" not in answer.answer


def test_percentage_leaderboard_wording_preserves_sample_without_per_game_unit() -> None:
    answer = _answer_text(
        {
            "type": "leaderboard",
            "stat": "true_shooting_percentage",
            "aggregation_mode": "average",
            "entries": [
                {
                    "player_name": "Jalen Brunson",
                    "display_values": {"true_shooting_percentage": "60.0%"},
                    "sample_size": 10,
                }
            ],
        }
    )
    assert answer == "Jalen Brunson led at 60.0% across 10 appearances."
