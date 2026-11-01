"""Advertised factual families answered by the deterministic analyst path.

Each case drives `resolve_query`, `AnalystTools` and `AnalystLoop` against real release
rows. They were written before the operation fixes, so threshold counts, player
leaderboards, shooting ratios, derived player counts, period scoring and the win/loss
split fail on the previous behaviour, which refused them for using words such as
"over", "under", "who led" or "shooting".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

ARCHIVE = (
    # date, home, away, home_score, away_score
    ("2025-11-01", "NYK", "BOS", 125, 110),
    ("2025-11-05", "BOS", "NYK", 98, 101),
    ("2025-11-10", "NYK", "DET", 118, 121),
    ("2025-11-15", "NYK", "ATL", 120, 95),
    ("2025-11-20", "MIA", "NYK", 130, 90),
    ("2025-11-25", "NYK", "CHI", 129, 99),
)

# name: minutes, points, rebounds, assists, steals, threes made, threes attempted, starter
BOX = {
    "Jalen Brunson": [
        (36, 30, 3, 10, 1, 3, 7, True),
        (36, 22, 2, 9, 2, 2, 6, True),
        (36, 25, 4, 8, 1, 4, 9, True),
        (36, 20, 3, 7, 0, 1, 4, True),
        (36, 18, 2, 6, 1, 2, 5, True),
        (36, 28, 5, 12, 2, 3, 8, True),
    ],
    "Karl-Anthony Towns": [
        (32, 12, 11, 4, 1, 1, 3, True),
        (32, 10, 10, 4, 0, 0, 2, True),
        (32, 9, 8, 4, 1, 1, 4, True),
        (0, 0, 0, 0, 0, 0, 0, True),
        (32, 8, 12, 4, 2, 0, 1, True),
        (32, 15, 10, 4, 1, 2, 5, True),
    ],
    "Josh Hart": [
        (30, 8, 6, 3, 1, 1, 2, True),
        (30, 9, 6, 2, 0, 0, 1, True),
        (30, 10, 7, 3, 2, 1, 3, True),
        (30, 7, 5, 1, 1, 0, 2, False),
        (30, 6, 4, 2, 0, 0, 1, True),
        (30, 11, 8, 4, 2, 2, 4, False),
    ],
    "Mikal Bridges": [
        (35, 14, 4, 2, 1, 3, 8, True),
        (35, 16, 5, 3, 0, 2, 4, True),
        (35, 20, 6, 2, 1, 5, 10, True),
        (35, 12, 3, 1, 2, 1, 5, True),
        (35, 10, 2, 2, 0, 0, 3, True),
        (35, 22, 5, 3, 1, 4, 9, True),
    ],
}

# Knicks points by quarter for the six archived games, and Knicks shooting by game.
PERIODS = {
    3: (28, 30, 25, 31, 22, 29),
    4: (26, 27, 24, 25, 20, 28),
}
SHOOTING = (  # field goals made, attempted, turnovers
    (44, 88, 12),
    (40, 85, 11),
    (40, 89, 13),
    (45, 90, 12),
    (33, 80, 15),
    (47, 95, 14),
)


_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"supported-families-test-{_SEED_COUNT}",
        season="2025-26",
        source="test",
        manifest_sha256=f"{_SEED_COUNT:064x}",
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    players = {
        player.full_name: player
        for player in (await db_session.execute(select(Player))).scalars().all()
    }
    for index, (day, home, away, home_score, away_score) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"families-{index}",
            season="2025-26",
            game_date=date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type="regular",
            data_status="analysis_ready",
            source_name="test",
            source_game_id=f"families-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        for name, games in BOX.items():
            minutes, points, rebounds, assists, steals, made, attempted, starter = games[index]
            db_session.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=players[name].id,
                    team_id="NYK",
                    starter=starter,
                    minutes=minutes,
                    points=points,
                    rebounds=rebounds,
                    assists=assists,
                    steals=steals,
                    three_pointers_made=made,
                    three_pointers_attempted=attempted,
                )
            )
        for period, series in PERIODS.items():
            db_session.add(
                PeriodScore(
                    release_id=release.id,
                    game_id=game.id,
                    team_id="NYK",
                    period=period,
                    points=series[index],
                )
            )
        made, attempted, turnovers = SHOOTING[index]
        db_session.add(
            TeamGameStat(
                release_id=release.id,
                game_id=game.id,
                team_id="NYK",
                points=home_score if home == "NYK" else away_score,
                field_goals_made=made,
                field_goals_attempted=attempted,
                three_pointers_made=0,
                three_pointers_attempted=0,
                free_throws_made=0,
                free_throws_attempted=0,
                turnovers=turnovers,
            )
        )
    await db_session.commit()
    return release


async def _deterministic(db_session, question: str):
    release = await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "supported-families-test"
    return tools, loop, await loop.run(allow_model=False)


def _claims(result) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for citation in result["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            grouped.setdefault(claim["metric_id"], []).append(claim)
    return grouped


def _game_ids(tools: AnalystTools, *days: str) -> list[int]:
    wanted = set(days)
    return sorted(game.id for game in tools.games if game.game_date.isoformat() in wanted)


async def test_score_threshold_counts_games_over_a_cutoff(db_session):
    tools, _, result = await _deterministic(
        db_session, "How many games did the Knicks score at least 120?"
    )
    claim = _claims(result)["games"][0]
    assert claim["value"] == 3
    assert claim["unit"] == "games"
    assert claim["denominator"] == 6 and claim["sample_size"] == 3
    assert claim["game_ids"] == _game_ids(tools, "2025-11-01", "2025-11-15", "2025-11-25")
    assert "3 of 6" in result["answer"]
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_opponent_threshold_counts_points_allowed(db_session):
    tools, _, result = await _deterministic(
        db_session, "How many games did the Knicks hold opponents under 100?"
    )
    claim = _claims(result)["games"][0]
    assert claim["value"] == 3
    assert claim["denominator"] == 6
    assert claim["game_ids"] == _game_ids(tools, "2025-11-05", "2025-11-15", "2025-11-25")
    assert claim["eligibility"]["subject"] == "opponent_points"
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_margin_threshold_counts_wins_by_margin(db_session):
    tools, _, result = await _deterministic(
        db_session, "How many games did the Knicks win by at least 20?"
    )
    claim = _claims(result)["games"][0]
    assert claim["value"] == 2
    assert claim["game_ids"] == _game_ids(tools, "2025-11-15", "2025-11-25")
    assert claim["eligibility"]["subject"] == "margin"
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_assists_leaderboard_names_the_leader_with_totals(db_session):
    tools, _, result = await _deterministic(db_session, "Who led the Knicks in assists?")
    claim = _claims(result)["assists:leader"][0]
    brunson = (
        await db_session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
    ).scalar_one()
    assert claim["value"] == {"name": "Jalen Brunson", "total": 52}
    assert claim["subject_id"] == f"player:{brunson.id}"
    assert claim["unit"] == "assists"
    assert claim["sample_size"] == 6 and claim["denominator"] == 6
    assert "Jalen Brunson" in result["answer"]
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_leaderboard_window_restricts_to_requested_games(db_session):
    _, _, result = await _deterministic(
        db_session, "Who led the team in scoring over the last 3 games?"
    )
    claim = _claims(result)["points:leader"][0]
    assert claim["value"] == {"name": "Jalen Brunson", "total": 66}
    assert claim["sample_size"] == 3


async def test_three_point_percentage_is_a_ratio_not_a_total(db_session):
    _, _, result = await _deterministic(
        db_session, "What was Mikal Bridges' three-point percentage?"
    )
    claim = _claims(result)["three_pointers_made:percentage"][0]
    assert claim["value"] == pytest.approx(100 * 15 / 39)
    assert claim["unit"] == "percent"
    assert claim["value"] != 15
    assert claim["sample_size"] == 6


async def test_double_doubles_are_derived_from_appearances(db_session):
    _, _, result = await _deterministic(db_session, "How many double-doubles did Towns have?")
    claim = _claims(result)["double_doubles"][0]
    assert claim["value"] == 3
    assert claim["unit"] == "count"
    assert claim["sample_size"] == 5
    assert "zero minutes" in " ".join(claim["coverage_limitations"]).lower()


async def test_games_started_counts_starter_rows(db_session):
    _, _, result = await _deterministic(db_session, "How many games did Josh Hart start?")
    claim = _claims(result)["starts"][0]
    assert claim["value"] == 4
    assert claim["unit"] == "starts"
    assert claim["sample_size"] == 6


async def test_period_scoring_comparison_uses_period_rows(db_session):
    _, _, result = await _deterministic(
        db_session, "Compare the Knicks' third-quarter and fourth-quarter scoring."
    )
    claims = _claims(result)["period:points"]
    by_period = {tuple(claim["filters"]["periods"]): claim for claim in claims}
    assert by_period[(3,)]["value"] == pytest.approx(165 / 6)
    assert by_period[(4,)]["value"] == pytest.approx(150 / 6)
    assert all(claim["denominator"] == 6 for claim in claims)
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_shooting_split_reports_both_results(db_session):
    _, _, result = await _deterministic(
        db_session, "Did the Knicks shoot better in wins or losses?"
    )
    claims = _claims(result)["field_goal_percentage"]
    by_result = {claim["filters"]["game_result"]: claim for claim in claims}
    assert by_result["win"]["value"] == pytest.approx(100 * 176 / 358)
    assert by_result["loss"]["value"] == pytest.approx(100 * 73 / 169)
    assert by_result["win"]["denominator"] == 4
    assert by_result["loss"]["denominator"] == 2
    assert all(claim["unit"] == "percent" for claim in claims)


async def test_result_split_reports_requested_counts(db_session):
    _, _, result = await _deterministic(
        db_session, "Compare wins and losses by average turnover count."
    )
    claims = _claims(result)["turnovers:average"]
    by_result = {claim["filters"]["game_result"]: claim for claim in claims}
    assert by_result["win"]["value"] == pytest.approx(49 / 4)
    assert by_result["loss"]["value"] == pytest.approx(28 / 2)


async def test_player_scoring_average_stays_on_the_named_player(db_session):
    tools, _, result = await _deterministic(db_session, "What was Jalen Brunson's scoring average?")
    claims = _claims(result)
    assert "points:average" in claims
    claim = claims["points:average"][0]
    assert claim["subject_id"].startswith("player:")
    assert claim["value"] == pytest.approx((30 + 22 + 25 + 20 + 18 + 28) / 6)
    assert claim["denominator"] == 6
    assert tools.scope is not None and tools.scope.operation == "player_metric"


async def test_best_defensive_game_ranks_fewest_points_allowed(db_session):
    tools, _, result = await _deterministic(db_session, "Explain the Knicks' best defensive game.")
    claim = _claims(result)["opponent_points"][0]
    assert claim["value"] == 95
    assert claim["game_ids"] == _game_ids(tools, "2025-11-15")
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_undefined_superlative_clarifies_instead_of_refusing(db_session):
    _, loop, result = await _deterministic(db_session, "Describe the Knicks' worst third quarter.")
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert "quarter" in result["answer"].lower()
    assert {item.status for item in loop.results} == {"ambiguous_entity"}


async def test_live_and_betting_questions_refuse_honestly(db_session):
    for question in (
        "What is the live score tonight?",
        "What is the best betting line for tonight?",
        "Will the Knicks win their next game?",
    ):
        _, loop, result = await _deterministic(db_session, question)
        assert result["outcome"] == "refuse", question
        assert result["refused"] is True, question
        assert "archive" in result["answer"].lower(), question
        assert _claims(result) == {}, question
        assert {item.status for item in loop.results} == {"unsupported_metric_or_scope"}


async def test_previous_refusal_wordings_are_gone(db_session):
    for question in (
        "How many games did the Knicks score at least 120?",
        "How many games did the Knicks hold opponents under 100?",
        "Who led the Knicks in assists?",
        "Who led the Knicks in rebounds?",
        "Who led the Knicks in steals?",
    ):
        _, _, result = await _deterministic(db_session, question)
        answer = result["answer"].lower()
        assert "does not count games that cross" not in answer, question
        assert "cannot answer that specific ranking" not in answer, question
        assert result["outcome"] == "answer", question
        assert result["refused"] is False, question
