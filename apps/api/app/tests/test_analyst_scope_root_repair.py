"""Scope defects that handed back a wider population, a merged ask or a full game.

Each case drives `resolve_query`, `AnalystTools` and `AnalystLoop` against rows whose
scoped numbers differ from the release-wide ones: five Boston games but two in January and
two in the playoffs, a five-game window whose allowed total differs from its per-game mean,
and a pinned game whose minute-level slice is not a full-game box score. A premise counted
over the whole release, a comma that normalization erased before the measures were split, a
points-allowed sum served without being asked for, or a full-game statline reported for an
event interval fails here.
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
    ("2025-12-05", "NYK", "BOS", 110, 100, "regular"),
    ("2025-12-20", "ATL", "NYK", 90, 95, "regular"),
    ("2026-01-08", "BOS", "NYK", 95, 105, "regular"),
    ("2026-01-15", "NYK", "ATL", 99, 92, "regular"),
    ("2026-01-22", "NYK", "BOS", 99, 101, "regular"),
    ("2026-02-02", "NYK", "ATL", 105, 99, "regular"),
    ("2026-04-20", "BOS", "NYK", 88, 100, "playoffs"),
    ("2026-04-22", "NYK", "BOS", 90, 97, "playoffs"),
)

# The January Boston pair and the playoff Boston pair, each two games out of five against
# Boston in the release.
JANUARY_BOSTON = ("2026-01-08", "2026-01-22")
PLAYOFF_BOSTON = ("2026-04-20", "2026-04-22")

# The last five games of the release: their points allowed sum to 477, or 95.4 per game.
LAST_FIVE_ALLOWED = 477
LAST_FIVE_AVERAGE = 95.4

_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"scope-root-repair-{_SEED_COUNT}",
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
            nba_game_id=f"scope-repair-{index}",
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
            source_game_id=f"scope-repair-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        games.append(game)
    # One real appearance so the player is resolvable inside this release. The row is a
    # full-game line: a minute-level slice must never deliver it.
    db_session.add(
        PlayerGameStat(
            release_id=release.id,
            game_id=games[4].id,
            player_id=players["Jalen Brunson"].id,
            team_id="NYK",
            starter=True,
            minutes=36,
            points=31,
            rebounds=5,
            assists=7,
            steals=1,
            three_pointers_made=2,
            three_pointers_attempted=6,
        )
    )
    await db_session.commit()
    return release


async def _run(db_session, question: str, release=None):
    release = release or await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "scope-root-repair"
    return tools, loop, await loop.run(allow_model=False)


def _claims(result) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for citation in result["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            grouped.setdefault(claim["metric_id"], []).append(claim)
    return grouped


def _game_ids(tools: AnalystTools, *days: str) -> list[int]:
    wanted = set(days)
    return sorted(game.id for game in tools.games if game.game_date.isoformat() in wanted)


# --- a stated opponent count is a premise about the requested scope -------------------


async def test_stated_opponent_count_is_checked_inside_the_named_month(db_session):
    tools, _, result = await _run(
        db_session, "How did the Knicks do in the two games against Boston in January?"
    )
    assert tools.scope is not None
    # Two January games match the stated count even though the release holds five.
    assert tools.scope.requires_clarification is False
    claims = _claims(result)
    assert claims["wins"][0]["value"] == 1
    assert claims["losses"][0]["value"] == 1
    assert set(claims["wins"][0]["game_ids"]) == set(_game_ids(tools, *JANUARY_BOSTON))
    assert result["outcome"] == "answer"


async def test_stated_opponent_count_is_checked_inside_the_named_phase(db_session):
    tools, _, result = await _run(
        db_session, "How did the Knicks do in the two games against Boston in the playoffs?"
    )
    assert tools.scope is not None
    assert tools.scope.season_type == "playoffs"
    assert tools.scope.requires_clarification is False
    claims = _claims(result)
    assert claims["wins"][0]["value"] == 1
    assert claims["losses"][0]["value"] == 1
    assert set(claims["wins"][0]["game_ids"]) == set(_game_ids(tools, *PLAYOFF_BOSTON))


async def test_stated_opponent_count_still_questions_a_wrong_unscoped_count(db_session):
    tools, loop, result = await _run(
        db_session, "How did the Knicks do in the two games against Boston?"
    )
    assert tools.scope is not None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}
    # The question offers the five Boston games the whole release actually holds.
    assert len(tools.scope.clarification_options) == 5


# --- a compound ask keeps every measure it names --------------------------------------


@pytest.mark.parametrize(
    "question",
    (
        "What were the Knicks' average points, average margin this season?",
        "What were the Knicks' average points; average margin this season?",
    ),
)
async def test_compound_measures_survive_the_punctuation_they_were_joined_with(
    db_session, question
):
    tools, _, result = await _run(db_session, question)
    assert tools.scope is not None
    claims = _claims(result)
    # Both named measures are delivered, each with its own average.
    assert claims["points_per_game"][0]["value"] == pytest.approx(100.4)
    assert claims["margin_per_game"][0]["value"] == pytest.approx(5.1)
    assert claims["points_per_game"][0]["denominator"] == len(ARCHIVE)


# --- points allowed is a per-game measure unless the request says otherwise -----------


async def test_points_allowed_defaults_to_the_per_game_mean(db_session):
    tools, _, result = await _run(
        db_session, "What was the defense like over the last 5 games by points allowed?"
    )
    assert tools.scope is not None
    claims = _claims(result)
    assert set(claims) == {"points_allowed_per_game"}
    claim = claims["points_allowed_per_game"][0]
    # The delivered number is the per-game mean, not the summed points allowed (477).
    assert claim["value"] == pytest.approx(LAST_FIVE_AVERAGE)
    assert claim["value"] != LAST_FIVE_ALLOWED
    assert claim["denominator"] == 5


async def test_explicitly_requested_points_allowed_total_is_honoured(db_session):
    tools, _, result = await _run(
        db_session, "How many points did the Knicks allow over the last 5 games?"
    )
    assert tools.scope is not None
    claims = _claims(result)
    assert set(claims) == {"points_allowed"}
    assert claims["points_allowed"][0]["value"] == LAST_FIVE_ALLOWED


# --- an event interval is not a full-game box score -----------------------------------


@pytest.mark.parametrize(
    "question",
    (
        "What did Brunson do in the final two minutes of the 2026-01-22 game?",
        "How many points did Brunson score in the final two minutes of the 2026-01-22 game?",
        "How many rebounds did Brunson have in the last two minutes of the 2026-01-22 game?",
    ),
)
async def test_a_minute_slice_never_becomes_the_full_game_statline(db_session, question):
    tools, loop, result = await _run(db_session, question)
    assert tools.scope is not None
    # The verified game stays anchored even though the slice cannot be answered.
    assert tools.scope.game_ids == _game_ids(tools, "2026-01-22")
    assert tools.scope.requires_clarification is True
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}
    answer = result["answer"].lower()
    assert "31" not in answer


async def test_a_minute_slice_without_a_pinned_game_asks_for_the_game_and_interval(db_session):
    tools, _, result = await _run(
        db_session, "What did Brunson do in the final two minutes over the last 5 games?"
    )
    assert tools.scope is not None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    question = (tools.scope.clarification_question or "").lower()
    assert "game" in question and "interval" in question


async def test_run_clarification_asks_for_the_missing_game_and_interval(db_session):
    tools, _, result = await _run(db_session, "What was their biggest scoring run this season?")
    assert tools.scope is not None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    question = (tools.scope.clarification_question or "").lower()
    # A definition alone is not enough while the game and interval are unnamed.
    assert "definition" in question
    assert "game" in question and "interval" in question
