"""Scope composition: shared constraints, one window authority, and honest anchors.

Each case drives the public analyst seam (`resolve_query`, `AnalystTools`, `AnalystLoop`)
against a fixture with unequal home/away groups, Boston games inside and outside January,
a named-month interval that spans a missing month, and a player who has a DNP in the most
recent team game. A scope that replaces shared filters with the split axis, materializes a
window into game IDs before the calculation, truncates appearances before removing DNPs,
or inherits an anchor from another release fails here.
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
from sqlalchemy import select

# date, home, away, home_score, away_score, season_type
ARCHIVE = (
    ("2025-12-20", "NYK", "BOS", 100, 90, "regular"),
    ("2026-01-03", "BOS", "NYK", 95, 105, "regular"),
    ("2026-01-11", "NYK", "BOS", 88, 95, "regular"),
    ("2026-01-17", "NYK", "BOS", 104, 95, "regular"),
    ("2026-01-25", "NYK", "MIA", 120, 100, "regular"),
    ("2026-02-02", "BOS", "NYK", 110, 100, "regular"),
    ("2026-02-14", "NYK", "TOR", 99, 90, "regular"),
    ("2026-03-04", "NYK", "BOS", 101, 91, "regular"),
    ("2026-03-18", "NYK", "BOS", 90, 100, "regular"),
    ("2026-04-05", "BOS", "NYK", 100, 111, "regular"),
    ("2026-04-12", "NYK", "BOS", 115, 105, "regular"),
    ("2026-04-20", "NYK", "MIA", 97, 90, "regular"),
    ("2026-04-27", "NYK", "ATL", 121, 130, "regular"),
    ("2026-05-01", "ATL", "NYK", 100, 99, "regular"),
)

# The most recent team game (index 13) is a DNP, so the last three appearances end at 12.
BRUNSON_POINTS = {
    0: 5,
    1: 10,
    2: 15,
    3: 20,
    4: 25,
    5: 30,
    6: 35,
    7: 40,
    8: 45,
    9: 10,
    10: 20,
    11: 30,
    12: 40,
    13: 0,
}
BRUNSON_ASSISTS = {index: 10 for index in range(len(ARCHIVE))}
BRUNSON_ASSISTS[4] = 3
HART_ASSISTS = {index: 0 for index in range(len(ARCHIVE))}
HART_ASSISTS[4] = 12

_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"scope-composition-test-{_SEED_COUNT}",
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
    for index, (day, home, away, home_score, away_score, season_type) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"composition-{_SEED_COUNT}-{index}",
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
            source_game_id=f"composition-{_SEED_COUNT}-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        games.append(game)
    for index, game in enumerate(games):
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=players["Jalen Brunson"].id,
                team_id="NYK",
                starter=True,
                minutes=0 if index == 13 else 34,
                points=BRUNSON_POINTS[index],
                rebounds=4,
                assists=BRUNSON_ASSISTS[index],
                steals=1,
                three_pointers_made=2,
                three_pointers_attempted=6,
            )
        )
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=players["Josh Hart"].id,
                team_id="NYK",
                starter=True,
                minutes=32,
                points=10,
                rebounds=5,
                assists=HART_ASSISTS[index],
                steals=1,
                three_pointers_made=1,
                three_pointers_attempted=4,
            )
        )
    await db_session.commit()
    return release


async def _run(db_session, question: str, state: dict | None = None, release=None):
    release = release or await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, state or {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "scope-composition-test"
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


def _own_points(tools: AnalystTools, indices: range) -> list[int]:
    values = []
    for game in tools.games[indices[0] : indices[-1] + 1]:
        values.append(game.home_score if game.home_team_id == "NYK" else game.away_score)
    return values


def _evidence_games(tools: AnalystTools, claim: dict) -> set[int]:
    """The games whose rows the delivered value was computed from."""
    games: set[int] = set()
    for ref in claim["supporting_evidence_ids"]:
        item = tools.evidence[ref]
        for inner in item.metadata.get("source_evidence_ids") or [ref]:
            game_id = tools.evidence[inner].game_id
            assert game_id is not None, inner
            games.add(game_id)
    return games


async def test_comparison_keeps_the_shared_opponent_and_interval(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, grouped, scope_archive

    version, ids = await scope_archive(monkeypatch)
    result = await ask(client, "Compare home and away scoring against Boston in January.", version)
    claims = grouped(result, "points_per_game")
    assert set(claims) == {"home", "away"}
    assert claims["home"]["game_ids"] == sorted(ids[d] for d in ("2026-01-11", "2026-01-17"))
    assert claims["away"]["game_ids"] == [ids["2026-01-03"]]
    assert claims["home"]["value"] == pytest.approx(96)
    assert claims["away"]["value"] == pytest.approx(105)
    assert claims["home"]["eligibility"]["considered_games"] == 2
    assert claims["away"]["eligibility"]["considered_games"] == 1
    assert all(claim["release_id"] == version for claim in claims.values())


async def test_two_named_month_endpoints_are_one_inclusive_interval(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, scope_archive

    version, ids = await scope_archive(monkeypatch)
    result = await ask(
        client, "How many games did the Knicks play between January 1 and March 15?", version
    )
    claim = _claims(result)["games"][0]
    assert claim["value"] == 7
    assert claim["game_ids"] == sorted(
        ids[d]
        for d in (
            "2026-01-03",
            "2026-01-11",
            "2026-01-17",
            "2026-01-25",
            "2026-02-02",
            "2026-02-14",
            "2026-03-04",
        )
    )
    assert claim["release_id"] == version


async def test_from_through_month_day_endpoints_keep_every_inner_game(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, scope_archive

    version, ids = await scope_archive(monkeypatch)
    result = await ask(
        client, "What was the Knicks record from January 1 through January 31?", version
    )
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (3, 1)
    assert set(wins["game_ids"]) | set(losses["game_ids"]) == {
        ids[d] for d in ("2026-01-03", "2026-01-11", "2026-01-17", "2026-01-25")
    }
    assert wins["release_id"] == losses["release_id"] == version


async def test_first_window_average_uses_the_first_games(db_session):
    tools, _, result = await _run(
        db_session, "What was the Knicks average scoring in the first 10 games?"
    )
    scope = tools.scope
    assert scope is not None
    assert (scope.relative_game_count, scope.relative_game_position) == (10, "first")
    assert scope.game_ids == []
    claim = _claims(result)["points_per_game"][0]
    expected = sum(_own_points(tools, range(0, 10))) / 10
    assert claim["value"] == pytest.approx(expected)
    assert claim["denominator"] == 10
    assert set(claim["game_ids"]) == {game.id for game in tools.games[:10]}


async def test_first_window_player_metric_uses_the_first_games(db_session):
    tools, _, result = await _run(
        db_session, "What was Brunson's average points in the first 3 games?"
    )
    scope = tools.scope
    assert scope is not None
    assert scope.operation == "player_metric"
    claim = _claims(result)["points:average"][0]
    assert claim["value"] == pytest.approx((5 + 10 + 15) / 3)
    assert claim["sample_size"] == 3
    assert set(claim["game_ids"]) == {game.id for game in tools.games[:3]}


async def test_window_composes_with_the_shared_opponent_and_side(db_session):
    tools, _, result = await _run(
        db_session, "What was their average scoring in the first 3 home games against Boston?"
    )
    scope = tools.scope
    assert scope is not None
    assert (scope.opponent_id, scope.home_away) == ("BOS", "home")
    claim = _claims(result)["points_per_game"][0]
    first_home_boston = [
        game for game in tools.games if game.home_team_id == "NYK" and game.away_team_id == "BOS"
    ][:3]
    expected = sum(game.home_score for game in first_home_boston) / 3
    assert claim["value"] == pytest.approx(expected, abs=0.05)
    assert set(claim["game_ids"]) == {game.id for game in first_home_boston}


async def test_leaderboard_ranks_inside_the_requested_best_win(db_session):
    tools, _, result = await _run(db_session, "Who led the Knicks in assists in their best win?")
    scope = tools.scope
    assert scope is not None and scope.operation == "player_leaderboard"
    best_win = max(
        tools.games,
        key=lambda game: (
            tools.score(game)[0] - tools.score(game)[1],
            game.game_date,
            game.id,
        ),
    )
    assert scope.game_ids == [best_win.id]
    claims = _claims(result)["assists:leader"]
    assert len(claims) == 1
    assert claims[0]["value"]["name"] == "Josh Hart"
    assert claims[0]["value"]["total"] == 12
    assert claims[0]["game_ids"] == [best_win.id]


async def test_player_comparison_windows_appearances_after_removing_dnps(db_session):
    tools, _, result = await _run(
        db_session, "Compare Brunson's scoring in the last 3 games with his season average."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert scope.comparison.measure == "player_metric"
    grouped = {
        claim["eligibility"]["comparison_group"]: claim
        for claim in _claims(result)["points:average"]
    }
    windowed = next(claim for key, claim in grouped.items() if key.startswith("last:"))
    # The most recent team game is a DNP: the window still holds three appearances.
    assert windowed["sample_size"] == 3
    assert windowed["value"] == pytest.approx((20 + 30 + 40) / 3, abs=0.05)
    assert _evidence_games(tools, windowed) == set(
        _game_ids(tools, "2026-04-12", "2026-04-20", "2026-04-27")
    )


async def test_month_to_month_wording_is_one_calendar_interval(db_session):
    tools, _, result = await _run(
        db_session, "How many games did the Knicks play from January through March?"
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is None
    assert (scope.date_start, scope.date_end) == (date(2026, 1, 1), date(2026, 3, 31))
    claim = _claims(result)["games"][0]
    assert claim["value"] == 8
    assert set(claim["game_ids"]) == set(
        _game_ids(
            tools,
            "2026-01-03",
            "2026-01-11",
            "2026-01-17",
            "2026-01-25",
            "2026-02-02",
            "2026-02-14",
            "2026-03-04",
            "2026-03-18",
        )
    )


async def test_named_months_without_a_comparison_ask_clarify(db_session):
    tools, loop, result = await _run(
        db_session, "How many games did the Knicks play in January and March?"
    )
    scope = tools.scope
    assert scope is not None
    assert scope.comparison is None
    assert scope.requires_clarification is True
    assert scope.clarification_reason == "ambiguous_interval"
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}


async def test_explicit_year_is_honoured_for_a_named_month(db_session):
    tools, _, result = await _run(db_session, "What was the Knicks record in January 2026?")
    scope = tools.scope
    assert scope is not None and scope.comparison is None
    wins, losses = _claims(result)["wins"][0], _claims(result)["losses"][0]
    assert (wins["value"], losses["value"]) == (3, 1)
    assert set(wins["game_ids"]) | set(losses["game_ids"]) == set(
        _game_ids(tools, "2026-01-03", "2026-01-11", "2026-01-17", "2026-01-25")
    )

    dated, _, dated_result = await _run(
        db_session,
        "How many games did the Knicks play between January 1, 2026 and March 15, 2026?",
        release=tools.release,
    )
    assert dated.scope is not None and dated.scope.comparison is None
    assert dated.scope.requires_clarification is False
    assert _claims(dated_result)["games"][0]["value"] == 7


async def test_a_year_outside_the_release_asks_instead_of_answering(db_session):
    tools, loop, result = await _run(
        db_session, "How many games did the Knicks play in January 2024?"
    )
    scope = tools.scope
    assert scope is not None
    assert scope.requires_clarification is True
    assert scope.clarification_reason == "outside_archive"
    assert "2024" in (scope.clarification_question or "")
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}


async def test_explicit_new_interval_clears_the_previous_game_anchor(db_session):
    release = await _seed_archive(db_session)
    first, _, _ = await _run(db_session, "What happened on 2026-01-11?", release=release)
    assert first.scope is not None and first.scope.game_ids == _game_ids(first, "2026-01-11")
    tools, _, result = await _run(
        db_session,
        "And what were Brunson's average points between March 1 and March 15?",
        state=dict(first.state),
        release=release,
    )
    scope = tools.scope
    assert scope is not None
    assert (scope.date_start, scope.date_end) == (date(2026, 3, 1), date(2026, 3, 15))
    assert scope.game_ids == _game_ids(tools, "2026-03-04")
    claim = _claims(result)["points:average"][0]
    assert claim["value"] == pytest.approx(40.0)
    assert claim["game_ids"] == _game_ids(tools, "2026-03-04")


async def test_new_window_after_an_anchored_turn_uses_the_season_population(db_session):
    release = await _seed_archive(db_session)
    first, _, _ = await _run(db_session, "What happened on 2026-01-11?", release=release)
    tools, _, result = await _run(
        db_session,
        "And what was their average scoring in the last 3 games?",
        state=dict(first.state),
        release=release,
    )
    scope = tools.scope
    assert scope is not None
    assert (scope.relative_game_count, scope.relative_game_position) == (3, "last")
    assert scope.game_ids == []
    assert scope.date_start is None and scope.date_end is None
    claim = _claims(result)["points_per_game"][0]
    assert claim["value"] == pytest.approx(sum(_own_points(tools, range(11, 14))) / 3, abs=0.05)


async def test_previous_release_anchor_is_not_inherited(db_session):
    first_release = await _seed_archive(db_session)
    first, _, _ = await _run(db_session, "What happened on 2026-01-11?", release=first_release)
    state = dict(first.state)
    next_release = await _seed_archive(db_session)
    tools, loop, result = await _run(
        db_session, "And how did JB play in that game?", state=state, release=next_release
    )
    scope = tools.scope
    assert scope is not None
    assert scope.game_ids == []
    assert scope.clarification_reason == "missing_reference"
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}
