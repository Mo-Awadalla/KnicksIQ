"""Scope resolution for date windows, ranges, aliases and referential follow-ups.

Each case drives `resolve_query`, `AnalystTools` and `AnalystLoop` against a fixture whose
records are known per window, so a full-season population substituted for a requested
window, an unparsed month-day endpoint, an unasked paired metric, or an unanchored
referential answer fails here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.query_resolution import resolve_query
from sqlalchemy import select

# date, home, away, season_type, Knicks result
ARCHIVE = (
    ("2025-10-25", "NYK", "BOS", "regular", "L"),
    ("2025-10-28", "BOS", "NYK", "regular", "L"),
    ("2025-11-02", "NYK", "BOS", "regular", "W"),
    ("2025-11-09", "BOS", "NYK", "regular", "L"),
    ("2025-11-16", "NYK", "BOS", "regular", "W"),
    ("2025-12-01", "ATL", "NYK", "regular", "W"),
    ("2025-12-15", "NYK", "BOS", "regular", "W"),
    ("2026-01-05", "BOS", "NYK", "regular", "W"),
    ("2026-01-12", "NYK", "BOS", "regular", "L"),
    ("2026-01-20", "BOS", "NYK", "regular", "W"),
    ("2026-01-28", "NYK", "BOS", "regular", "W"),
    ("2026-02-08", "ATL", "NYK", "regular", "L"),
    ("2026-02-20", "NYK", "BOS", "regular", "W"),
    ("2026-03-05", "BOS", "NYK", "regular", "W"),
    ("2026-03-12", "NYK", "BOS", "regular", "L"),
    ("2026-03-20", "BOS", "NYK", "regular", "W"),
    ("2026-04-10", "NYK", "BOS", "regular", "W"),
    ("2026-06-01", "BOS", "NYK", "playoffs", "W"),
)

BRUNSON = {7: 30, 8: 20, 9: 25}

_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"scope-windows-test-{_SEED_COUNT}",
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
    games: list[Game] = []
    for index, (day, home, away, season_type, outcome) in enumerate(ARCHIVE):
        won = outcome == "W"
        home_score, away_score = (
            ((110, 100) if won else (95, 105))
            if home == "NYK"
            else ((95, 105) if won else (110, 100))
        )
        game = Game(
            release_id=release.id,
            nba_game_id=f"windows-{index}",
            season="2025-26",
            game_date=date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type=season_type,
            data_status="analysis_ready",
            source_name="test",
            source_game_id=f"windows-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        games.append(game)
    for index, points in BRUNSON.items():
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=games[index].id,
                player_id=players["Jalen Brunson"].id,
                team_id="NYK",
                starter=True,
                minutes=36,
                points=points,
                rebounds=4,
                assists=6,
                steals=1,
                three_pointers_made=2,
                three_pointers_attempted=6,
            )
        )
    await db_session.commit()
    return release


async def _run(db_session, question: str, state: dict | None = None, release=None):
    release = release or await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, state or {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "scope-windows-test"
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


def _window_ids(tools: AnalystTools, start: int, end: int) -> list[int]:
    return [game.id for game in tools.games[start:end]]


async def test_first_ten_games_use_the_first_ten_chronological_games(db_session):
    tools, _, result = await _run(db_session, "What was their record in the first 10 games?")
    assert tools.scope is not None
    assert tools.scope.relative_game_count == 10
    assert tools.scope.relative_game_position == "first"
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (6, 4)
    assert set(wins["game_ids"]) == set(_window_ids(tools, 0, 10))
    assert wins["eligibility"]["considered_game_ids"] == _window_ids(tools, 0, 10)
    assert result["outcome"] == "answer"


async def test_final_regular_season_window_excludes_the_playoffs_and_earlier_games(db_session):
    tools, _, result = await _run(
        db_session, "What was their record over the final 15 regular-season games?"
    )
    assert tools.scope is not None
    assert tools.scope.relative_game_count == 15
    assert tools.scope.relative_game_position == "last"
    assert tools.scope.season_type == "regular"
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (11, 4)
    assert set(wins["game_ids"]) == set(_window_ids(tools, 2, 17))
    assert _game_ids(tools, "2026-06-01")[0] not in wins["game_ids"]


async def test_month_day_range_counts_only_games_inside_the_interval(db_session):
    tools, _, result = await _run(
        db_session, "How many games did they play between March 1 and March 15?"
    )
    assert tools.scope is not None
    assert tools.scope.date_start == date(2026, 3, 1)
    assert tools.scope.date_end == date(2026, 3, 15)
    claim = _claims(result)["games"][0]
    assert claim["value"] == 2
    assert set(claim["game_ids"]) == set(_game_ids(tools, "2026-03-05", "2026-03-12"))


async def test_named_month_day_range_reports_the_record_not_the_whole_month(db_session):
    tools, _, result = await _run(
        db_session, "How did the Knicks perform from January 1 through January 31?"
    )
    assert tools.scope is not None
    assert tools.scope.operation == "team_record"
    assert (tools.scope.date_start, tools.scope.date_end) == (date(2026, 1, 1), date(2026, 1, 31))
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (3, 1)
    assert set(wins["game_ids"]) == set(
        _game_ids(tools, "2026-01-05", "2026-01-12", "2026-01-20", "2026-01-28")
    )


async def test_after_the_all_star_break_starts_at_the_archive_boundary(db_session):
    tools, _, result = await _run(db_session, "What was their record after the All-Star break?")
    assert tools.scope is not None
    assert tools.scope.relative_game_count is None
    assert tools.scope.date_start == date(2026, 2, 20)
    assert tools.scope.date_end is None
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (5, 1)
    assert set(wins["game_ids"]) == set(_window_ids(tools, 12, 18))


async def test_road_wins_inside_a_month_keep_both_filters(db_session):
    tools, _, result = await _run(db_session, "How many road games did they win in December?")
    assert tools.scope is not None
    assert (tools.scope.home_away, tools.scope.game_result) == ("away", "W")
    claim = _claims(result)["wins"][0]
    assert claim["value"] == 1
    assert set(claim["game_ids"]) == set(_game_ids(tools, "2025-12-01"))


async def test_average_margin_over_the_last_eight_games(db_session):
    tools, _, result = await _run(
        db_session, "What was their average margin over the last 8 games?"
    )
    assert tools.scope is not None
    assert tools.scope.relative_game_count == 8
    claim = _claims(result)["margin_per_game"][0]
    assert claim["value"] == pytest.approx(5.0)
    assert claim["denominator"] == 8
    assert set(claim["game_ids"]) == set(_window_ids(tools, 10, 18))


@pytest.mark.parametrize(
    ("question", "opponent", "record"),
    (
        ("How did NYK do vs BOS?", "BOS", (11, 5)),
        ("How did they do v ATL?", "ATL", (1, 1)),
    ),
)
async def test_do_versus_alias_answers_only_the_opponent_record(
    db_session, question, opponent, record
):
    tools, _, result = await _run(db_session, question)
    assert tools.scope is not None
    assert tools.scope.operation == "team_record"
    assert tools.scope.opponent_id == opponent
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == record


async def test_opponent_record_emits_no_unrequested_aggregate(db_session):
    tools, _, result = await _run(db_session, "How did NYK do vs BOS?")
    assert tools.scope is not None
    assert set(_claims(result)) == {"wins", "losses"}


async def test_average_score_returns_only_the_requested_average(db_session):
    tools, _, result = await _run(db_session, "What was the Knicks average score per game?")
    assert tools.scope is not None
    claims = _claims(result)
    assert set(claims) == {"points_per_game"}
    assert claims["points_per_game"][0]["value"] == pytest.approx(1875 / 18, abs=0.05)


async def test_total_points_returns_only_the_requested_total(db_session):
    tools, _, result = await _run(db_session, "How many total points did the Knicks score?")
    assert tools.scope is not None
    claims = _claims(result)
    assert set(claims) == {"points"}
    assert claims["points"][0]["value"] == 1875


async def test_unanchored_referential_player_ask_clarifies_instead_of_a_season_metric(db_session):
    tools, loop, result = await _run(db_session, "How did JB play in that game?")
    assert tools.scope is not None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert tools.scope.clarification_reason == "missing_reference"
    assert {item.status for item in loop.results} == {"ambiguous_entity"}


async def test_referential_player_ask_inherits_the_verified_game(db_session):
    release = await _seed_archive(db_session)
    first, _, _ = await _run(db_session, "What happened on 2026-01-12?", release=release)
    assert first.scope is not None and first.scope.game_ids == _game_ids(first, "2026-01-12")
    tools, _, result = await _run(
        db_session, "How did JB play in that game?", state=dict(first.state), release=release
    )
    assert tools.scope is not None
    assert tools.scope.game_ids == _game_ids(tools, "2026-01-12")
    assert tools.scope.operation == "player_game_summary"
    claims = _claims(result)
    assert set(claims) == {"points:game", "rebounds:game", "assists:game", "game_score"}
    assert claims["points:game"][0]["value"] == 20
    assert claims["rebounds:game"][0]["value"] == 4
    assert claims["assists:game"][0]["value"] == 6
    assert "per appearance" not in result["answer"].lower()
    assert all(
        claim["game_ids"] == _game_ids(tools, "2026-01-12")
        for group in claims.values()
        for claim in group
    )


async def test_first_window_resolves_without_a_comparison(db_session):
    release = await _seed_archive(db_session)
    resolved = await resolve_query(
        db_session,
        "What was their record in the first 10 games?",
        intent="analyst",
        data_version=release.version,
    )
    assert resolved.relative_game_count == 10
    assert resolved.relative_game_position == "first"
    assert resolved.comparison is None
