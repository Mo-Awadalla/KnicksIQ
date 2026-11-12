"""Grouped comparisons answered from separate populations with their own denominators.

Every case drives `resolve_query`, `AnalystTools` and `AnalystLoop` against real fixture
rows. The fixture has unequal group sizes (5 home games, 3 away games, 3 Boston games, 2
Toronto games), a mid-February schedule gap that defines the All-Star boundary, a playoff
game after the break, and a zero-minute bench row, so a collapsed single population, a
summing comparison, or a per-appearance bench denominator fails here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_fallback import fallback_claims
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolResult
from app.services.query_comparisons import group_games
from sqlalchemy import select

# date, home, away, home_score, away_score, season_type
ARCHIVE = (
    ("2025-11-01", "NYK", "BOS", 110, 100, "regular"),
    ("2025-11-05", "BOS", "NYK", 90, 120, "regular"),
    ("2025-11-10", "NYK", "TOR", 100, 101, "regular"),
    ("2025-11-15", "NYK", "TOR", 99, 97, "regular"),
    ("2026-01-20", "NYK", "MIA", 130, 120, "regular"),
    ("2026-02-10", "LAL", "NYK", 90, 100, "regular"),
    ("2026-02-20", "DEN", "NYK", 99, 88, "regular"),
    ("2026-06-10", "NYK", "BOS", 105, 95, "playoffs"),
)

# name: game index -> (points, minutes, starter)
BOX = {
    "Mikal Bridges": {
        0: (12, 30, True),
        1: (8, 30, True),
        2: (10, 30, True),
        4: (10, 30, True),
        6: (20, 25, True),
        7: (0, 0, True),
    },
    "Precious Achiuwa": {
        0: (12, 20, False),
        1: (20, 22, False),
        2: (15, 20, False),
        3: (0, 0, False),
        4: (10, 18, False),
        5: (12, 20, False),
    },
    "Donte DiVincenzo": {0: (8, 18, False), 1: (10, 16, False)},
}

_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"comparison-test-{_SEED_COUNT}",
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
            nba_game_id=f"comparison-{index}",
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
            source_game_id=f"comparison-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        games.append(game)
    for name, rows in BOX.items():
        for index, (points, minutes, starter) in rows.items():
            db_session.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=games[index].id,
                    player_id=players[name].id,
                    team_id="NYK",
                    starter=starter,
                    minutes=minutes,
                    points=points,
                    rebounds=0,
                    assists=0,
                    steals=0,
                    three_pointers_made=0,
                    three_pointers_attempted=0,
                )
            )
    await db_session.commit()
    return release


async def _run(db_session, question: str):
    release = await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "comparison-test"
    return tools, loop, await loop.run(allow_model=False)


def _claims(result) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for citation in result["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            grouped.setdefault(claim["metric_id"], []).append(claim)
    return grouped


def _by_group(claims: list) -> dict[str, dict]:
    return {claim["eligibility"]["comparison_group"]: claim for claim in claims}


def _game_ids(tools: AnalystTools, *days: str) -> list[int]:
    wanted = set(days)
    return sorted(game.id for game in tools.games if game.game_date.isoformat() in wanted)


async def test_home_and_away_keep_separate_populations(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, comparison_archive

    version, ids = await comparison_archive(monkeypatch)
    result = await ask(client, "Compare the Knicks' offense at home and on the road.", version)
    assert set(_claims(result)) == {"points_per_game"}
    claims = _by_group(_claims(result)["points_per_game"])
    home, away = claims["home"], claims["away"]
    assert home["value"] == pytest.approx(108.8)
    assert away["value"] == pytest.approx(102.7)
    assert (home["sample_size"], home["denominator"]) == (5, 5)
    assert (away["sample_size"], away["denominator"]) == (3, 3)
    assert home["game_ids"] == sorted(
        ids[day] for day in ("2025-11-01", "2025-11-10", "2025-11-15", "2026-01-20", "2026-06-10")
    )
    assert away["game_ids"] == sorted(
        ids[day] for day in ("2025-11-05", "2026-02-10", "2026-02-20")
    )
    assert home["release_id"] == away["release_id"] == version


async def test_two_opponent_comparison_never_sums_the_groups(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, comparison_archive

    version, ids = await comparison_archive(monkeypatch)
    result = await ask(client, "Did the Knicks play better against Boston or Toronto?", version)
    claims = _claims(result)
    assert set(claims) == {"wins", "losses", "margin_per_game"}
    wins = _by_group(claims["wins"])
    losses = _by_group(claims["losses"])
    margin = _by_group(claims["margin_per_game"])
    assert (wins["BOS"]["value"], losses["BOS"]["value"]) == (3, 0)
    assert (wins["TOR"]["value"], losses["TOR"]["value"]) == (1, 1)
    assert margin["BOS"]["value"] == pytest.approx(16.7)
    assert margin["TOR"]["value"] == pytest.approx(0.5)
    assert margin["BOS"]["denominator"] == 3 and margin["TOR"]["denominator"] == 2
    assert "better" in " ".join(margin["BOS"]["coverage_limitations"]).lower()
    assert margin["BOS"]["game_ids"] == sorted(
        ids[d] for d in ("2025-11-01", "2025-11-05", "2026-06-10")
    )
    assert margin["TOR"]["game_ids"] == sorted(ids[d] for d in ("2025-11-10", "2025-11-15"))
    assert all(claim["release_id"] == version for claim in margin.values())


async def test_first_and_last_window_comparison_honours_direction(client, monkeypatch):
    from app.tests.support.analytics_workflows import ask, comparison_archive

    version, ids = await comparison_archive(monkeypatch)
    result = await ask(client, "Compare their first 2 games with their last 2 games.", version)
    claims = _claims(result)
    assert set(claims) == {"wins", "losses"}
    wins = _by_group(claims["wins"])
    losses = _by_group(claims["losses"])
    assert (wins["first:2"]["value"], losses["first:2"]["value"]) == (2, 0)
    assert (wins["last:2"]["value"], losses["last:2"]["value"]) == (1, 1)
    assert wins["first:2"]["game_ids"] == sorted(ids[d] for d in ("2025-11-01", "2025-11-05"))
    assert wins["last:2"]["game_ids"] == sorted(ids[d] for d in ("2026-02-20", "2026-06-10"))
    assert wins["first:2"]["release_id"] == wins["last:2"]["release_id"] == version


async def test_all_star_comparison_uses_the_archive_break_and_its_coverage(db_session):
    tools, _, result = await _run(
        db_session, "Compare Mikal Bridges' scoring before and after the All-Star break."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert scope.comparison.measure == "player_metric"
    assert [group.key for group in scope.comparison.groups] == ["before_all_star", "after_all_star"]
    assert scope.comparison.break_before == date(2026, 2, 10)
    assert scope.comparison.break_after == date(2026, 2, 20)
    # The released population is the default coverage, so the playoff game after the
    # break stays inside the after group.
    assert scope.comparison.coverage == "release"

    claims = _by_group(_claims(result)["points:average"])
    before, after = claims["before_all_star"], claims["after_all_star"]
    assert before["value"] == pytest.approx(40 / 4)
    assert after["value"] == pytest.approx(20 / 1)
    assert before["sample_size"] == 4 and after["sample_size"] == 1
    assert after["denominator"] == 1
    assert "zero minutes" in " ".join(after["coverage_limitations"]).lower()


async def test_bench_comparison_divides_by_team_games(db_session):
    tools, _, result = await _run(
        db_session, "Was the bench more productive in home or away games?"
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert scope.comparison.measure == "bench_points"

    # One scalar fact per group: 45 bench points over five home games, not over four
    # bench appearances, with no hidden zero-minute count.
    claims = _claims(result)
    assert set(claims) == {"bench_points_per_team_game"}
    grouped = _by_group(claims["bench_points_per_team_game"])
    home, away = grouped["home"], grouped["away"]
    assert home["value"] == pytest.approx(45 / 5)
    assert (home["denominator"], home["sample_size"]) == (5, 4)
    assert away["value"] == pytest.approx(42 / 3)
    assert (away["denominator"], away["sample_size"]) == (3, 3)
    assert home["unit"] == "points per game"
    assert isinstance(home["value"], float) and isinstance(away["value"], float)


async def test_conference_comparison_uses_the_team_domain_mapping(db_session):
    tools, _, result = await _run(
        db_session, "Did the Knicks fare better against Eastern or Western teams?"
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert [group.key for group in scope.comparison.groups] == ["East", "West"]
    assert tools.conferences["LAL"] == "West" and tools.conferences["BOS"] == "East"

    claims = _claims(result)
    assert set(claims) == {"wins", "losses", "margin_per_game"}
    wins = _by_group(claims["wins"])
    losses = _by_group(claims["losses"])
    margin = _by_group(claims["margin_per_game"])
    assert (wins["East"]["value"], losses["East"]["value"]) == (5, 1)
    assert (wins["West"]["value"], losses["West"]["value"]) == (1, 1)
    assert margin["East"]["value"] == pytest.approx(round(61 / 6, 1))
    assert margin["West"]["value"] == pytest.approx(-0.5)
    assert margin["East"]["eligibility"]["considered_games"] == 6
    assert margin["West"]["eligibility"]["considered_games"] == 2


async def test_month_comparison_uses_named_months(db_session):
    tools, _, result = await _run(
        db_session, "Compare their January record with their February record."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert [group.key for group in scope.comparison.groups] == ["month:1", "month:2"]

    # A named month splits a record, so each month reports wins and losses.
    claims = _claims(result)
    assert set(claims) == {"wins", "losses"}
    wins = _by_group(claims["wins"])
    losses = _by_group(claims["losses"])
    assert (wins["month:1"]["value"], losses["month:1"]["value"]) == (1, 0)
    assert (wins["month:2"]["value"], losses["month:2"]["value"]) == (1, 1)
    assert wins["month:1"]["game_ids"] == _game_ids(tools, "2026-01-20")
    assert wins["month:2"]["game_ids"] == _game_ids(tools, "2026-02-10", "2026-02-20")


async def test_false_game_count_premise_clarifies(db_session):
    tools, loop, result = await _run(db_session, "Compare the two Knicks games against Boston.")
    assert tools.scope is not None
    assert tools.scope.comparison is None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}
    assert any("2025-11-01" in choice for choice in tools.scope.clarification_options)


async def test_undefined_measure_comparisons_clarify(db_session):
    cases = {
        "Which was stronger: the Knicks offense or defense?": "measure",
        "Compare close games with blowouts.": "margin",
    }
    for question, marker in cases.items():
        tools, loop, result = await _run(db_session, question)
        assert tools.scope is not None and tools.scope.comparison is None, question
        assert result["outcome"] == "clarify", question
        assert marker in (tools.scope.clarification_question or "").lower(), question
        assert {item.status for item in loop.results} == {"ambiguous_entity"}, question


async def test_fallback_keeps_comparison_claims_inside_their_group(db_session):
    release = await _seed_archive(db_session)
    tools = AnalystTools(
        db_session,
        release,
        "Compare the Knicks' offense at home and on the road.",
        release.season,
        {},
    )
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "comparison-test"
    from app.services.evidence_contracts import ToolCall

    loop.results.append(
        await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    home = next(group for group in scope.comparison.groups if group.key == "home")
    away = next(group for group in scope.comparison.groups if group.key == "away")
    mixed = tools.claim(
        subject="team:NYK",
        metric="points_per_game",
        value=99.0,
        unit="points per game",
        games=group_games(scope.comparison, home, tools.games, tools.conferences)
        + group_games(scope.comparison, away, tools.games, tools.conferences),
        evidence=[tools.receipt(game) for game in tools.games],
        statement="Mixed population",
        scope=scope,
        sample=8,
        denominator=8,
        eligibility={
            "operation": "team_comparison",
            "comparison_group": "home",
            "measure": "scoring",
            "considered_games": 8,
        },
    )
    loop.results.append(ToolResult(status="ok", message="", claims=[mixed]))

    kept = fallback_claims(loop)
    assert {claim.eligibility["comparison_group"] for claim in kept} == {"home", "away"}
    assert mixed.claim_id not in {claim.claim_id for claim in kept}


async def test_unresolved_comparison_reports_the_empty_group(db_session):
    tools, _, _ = await _run(
        db_session, "Compare Mikal Bridges' scoring before and after the All-Star break."
    )
    assert tools.scope is not None and tools.scope.comparison is not None
    spec = tools.scope.comparison.model_copy(update={"break_after": date(2027, 1, 1)})
    scope = tools.scope.model_copy(update={"comparison": spec})
    from app.services.analyst_comparisons import compare

    outcome = await compare(tools, scope)
    assert outcome.status == "incomplete_coverage"
    assert "after_all_star" in outcome.message
