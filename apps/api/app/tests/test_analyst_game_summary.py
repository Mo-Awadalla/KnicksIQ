"""One archived game's player box score answered as a statline, and the asks that cannot be.

Each case drives `resolve_query`, `AnalystTools` and `AnalystLoop` against real release
rows. They were written before the operation existed, so the broad "what did he do in that
game" family currently delivers a single per-appearance average while the pinned narrative
turn delivers a record, a points total and a margin it was never asked for.

The delivered statline is the game's own box-score row: points, rebounds and assists, plus
that game's final score. Explicit metric asks stay that one metric, a broad ask without one
pinned game clarifies, and a key sequence with no supported event measure clarifies instead
of being answered as a record.
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
from app.services.query_operation_decisions import classify_operation
from sqlalchemy import select

# date, home, away, home_score, away_score
ARCHIVE = (
    ("2025-11-05", "NYK", "BOS", 101, 98),
    ("2025-11-20", "BOS", "NYK", 120, 90),
    ("2025-12-10", "NYK", "BKN", 128, 88),
    ("2026-01-08", "NYK", "DET", 110, 104),
)

# name: points, rebounds, assists per archived game, in ARCHIVE order
BOX = {
    "Karl-Anthony Towns": [(22, 9, 3), (18, 11, 2), (31, 14, 5), (25, 8, 4)],
    "Jalen Brunson": [(28, 3, 7), (20, 2, 9), (33, 4, 11), (26, 3, 8)],
}

# The biggest win (2025-12-10, +40) and the only archived Boston loss (2025-11-20).
BIGGEST_WIN = "2025-12-10"
BOSTON_LOSS = "2025-11-20"

_SEED_COUNT = 0


async def _seed_archive(db_session) -> DatasetRelease:
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"game-summary-test-{_SEED_COUNT}",
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
    for index, (day, home, away, home_score, away_score) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"summary-{index}",
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
            source_game_id=f"summary-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        games.append(game)
    for name, lines in BOX.items():
        for index, (points, rebounds, assists) in enumerate(lines):
            db_session.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=games[index].id,
                    player_id=players[name].id,
                    team_id="NYK",
                    starter=True,
                    minutes=34,
                    points=points,
                    rebounds=rebounds,
                    assists=assists,
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
    loop.request_id = "game-summary-test"
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


async def test_broad_ask_in_one_pinned_game_delivers_the_full_one_game_statline(db_session):
    tools, _, result = await _run(db_session, "What did Towns do in the biggest win?")
    assert tools.scope is not None
    assert tools.scope.operation == "player_game_summary"
    assert tools.scope.game_ids == _game_ids(tools, BIGGEST_WIN)
    claims = _claims(result)
    assert set(claims) == {
        "points:game",
        "rebounds:game",
        "assists:game",
        "game_score",
    }
    # The 2025-12-10 row is the game's own box score, not an average over appearances.
    points, rebounds, assists = (
        claims["points:game"][0],
        claims["rebounds:game"][0],
        claims["assists:game"][0],
    )
    assert (points["value"], rebounds["value"], assists["value"]) == (31, 14, 5)
    assert (points["unit"], rebounds["unit"], assists["unit"]) == (
        "points",
        "rebounds",
        "assists",
    )
    for claim in (points, rebounds, assists):
        assert claim["game_ids"] == _game_ids(tools, BIGGEST_WIN)
        assert claim["sample_size"] == 1
        assert claim["eligibility"]["operation"] == "player_game_summary"
        assert claim["release_id"] == tools.release.version
    assert points["subject_id"] == rebounds["subject_id"] == assists["subject_id"]
    assert points["subject_id"].startswith("player:")
    assert "per appearance" not in result["answer"].lower()
    assert "average" not in result["answer"].lower()
    assert "31 points" in result["answer"] and "14 rebounds" in result["answer"]
    assert "5 assists" in result["answer"] and BIGGEST_WIN in result["answer"]
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_the_summary_carries_that_games_real_scoreline(db_session):
    tools, _, result = await _run(db_session, "What did Towns do in the biggest win?")
    claim = _claims(result)["game_score"][0]
    assert claim["value"] == {
        "nba_game_id": "summary-2",
        "game_date": BIGGEST_WIN,
        "home_team_id": "NYK",
        "away_team_id": "BKN",
        "home_score": 128,
        "away_score": 88,
    }
    assert claim["game_ids"] == _game_ids(tools, BIGGEST_WIN)
    assert claim["eligibility"]["operation"] == "player_game_summary"
    assert "128" in result["answer"] and "88" in result["answer"]


async def test_the_statline_is_cited_to_the_games_own_box_score_row(db_session):
    tools, _, result = await _run(db_session, "What did Towns do in the biggest win?")
    claim = next(item for item in tools.claims.values() if item.metric_id == "points:game")
    receipts = [tools.evidence[ref] for ref in claim.supporting_evidence_ids]
    assert receipts
    assert any(
        receipt.metadata.get("points") == 31 and receipt.metadata.get("rebounds") == 14
        for receipt in receipts
    )
    assert all(receipt.release_id == tools.release.version for receipt in receipts)
    assert result["citations"]


async def test_an_explicit_metric_ask_stays_that_metric_without_extras(db_session):
    _, _, result = await _run(db_session, "How many points did Towns score in the biggest win?")
    claims = _claims(result)
    assert set(claims) == {"points:total"}
    assert claims["points:total"][0]["value"] == 31
    assert "rebounds" not in result["answer"].lower()
    assert "assists" not in result["answer"].lower()
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_an_explicit_average_ask_stays_an_average(db_session):
    _, _, result = await _run(db_session, "What was Towns' scoring average in the biggest win?")
    claims = _claims(result)
    assert set(claims) == {"points:average"}
    assert claims["points:average"][0]["value"] == pytest.approx(31.0)
    assert "rebounds" not in result["answer"].lower()


@pytest.mark.parametrize(
    "question",
    (
        "What was Towns' stat line?",
        "What did Towns do in that game?",
    ),
)
async def test_a_broad_ask_without_one_pinned_game_clarifies(db_session, question):
    tools, loop, result = await _run(db_session, question)
    assert tools.scope is not None
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}


async def test_a_broad_ask_never_reports_a_judgement_about_how_well_he_played(db_session):
    _, _, result = await _run(db_session, "Did Towns play well in the biggest win?")
    claims = _claims(result)
    assert set(claims) == {"points:game", "rebounds:game", "assists:game", "game_score"}
    answer = result["answer"].lower()
    for judgement in ("well", "great", "badly", "poorly", "excellent"):
        assert judgement not in answer
    assert result["outcome"] == "answer" and result["refused"] is False


async def test_a_later_pinned_game_never_reuses_the_earlier_statline(db_session):
    release = await _seed_archive(db_session)
    _, _, first = await _run(db_session, "What did Towns do in the biggest win?", release=release)
    assert _claims(first)["points:game"][0]["value"] == 31
    # The committed turn carries its claims and the verified game anchor forward.
    assert first["state"]["claims"]
    second, _, result = await _run(
        db_session,
        f"What did Towns do on {BOSTON_LOSS}?",
        state=dict(first["state"]),
        release=release,
    )
    assert second.scope is not None
    assert second.scope.game_ids == _game_ids(second, BOSTON_LOSS)
    claims = _claims(result)
    assert claims["points:game"][0]["value"] == 18
    assert claims["rebounds:game"][0]["value"] == 11
    assert claims["assists:game"][0]["value"] == 2
    expected = _game_ids(second, BOSTON_LOSS)
    assert all(item["game_ids"] == expected for group in claims.values() for item in group)
    assert claims["game_score"][0]["value"]["home_score"] == 120
    assert "14 rebounds" not in result["answer"]
    assert "31 points" not in result["answer"]


async def test_a_pinned_key_sequence_clarifies_instead_of_reporting_a_record(db_session):
    tools, loop, result = await _run(db_session, "What was the key sequence in the Boston loss?")
    assert tools.scope is not None
    # The known game stays anchored; only the missing event measure is asked for.
    assert tools.scope.game_ids == _game_ids(tools, BOSTON_LOSS)
    assert tools.scope.requires_clarification is True
    answer = result["answer"].lower()
    assert result["outcome"] == "clarify" and result["refused"] is False
    assert _claims(result) == {}
    assert {item.status for item in loop.results} == {"ambiguous_entity"}
    for unasked in ("knicks wins", "knicks losses", "knicks points", "margin:"):
        assert unasked not in answer


def test_the_summary_operation_is_typed_for_paraphrases_not_one_question():
    for question in (
        "What did Towns do in the biggest win?",
        "How did Brunson play in the biggest win?",
        "How did Brunson perform in the Boston game?",
        "What did Brunson put up on 2025-11-20?",
        "Did Brunson play well in the biggest win?",
        "What was Brunson's stat line in the biggest win?",
    ):
        decision = classify_operation(
            question, has_player=True, ambiguous_player=False, performance_scope="game"
        )
        assert decision.operation == "player_game_summary", question
        assert decision.reason is None and decision.clarification is None, question


def test_explicit_measures_never_become_the_summary_operation():
    for question in (
        "How many points did Towns score in the biggest win?",
        "What was Towns' scoring average in the biggest win?",
        "What was Towns' true shooting percentage in the biggest win?",
        "How many games did Towns score at least 20 in?",
        "Who led the Knicks in rebounds in the biggest win?",
    ):
        decision = classify_operation(
            question, has_player=True, ambiguous_player=False, performance_scope="game"
        )
        assert decision.operation != "player_game_summary", question


async def test_whole_season_followup_drops_game_anchor_but_keeps_player(db_session):
    first_tools, _, first = await _run(db_session, "What did Towns do in the biggest win?")
    _, _, result = await _run(
        db_session,
        "What was his average points over the whole season?",
        state=first["state"],
        release=first_tools.release,
    )
    claim = _claims(result)["points:average"][0]
    assert claim["value"] == 24
    assert claim["sample_size"] == 4
    assert claim["game_ids"] == sorted(game.id for game in first_tools.games)
