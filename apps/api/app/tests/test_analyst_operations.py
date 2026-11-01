"""Advertised question families answered through the real deterministic analyst path.

These are behaviour cases: each one drives `resolve_query`, `AnalystTools` and `AnalystLoop`
against real release rows, never a mocked calculation. They were written before the operation
fixes so the tied streaks, opponent scopes and paraphrases fail on the previous behaviour.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall

ARCHIVE = (
    # date, home, away, home_score, away_score
    ("2025-11-05", "NYK", "BOS", 112, 104),
    ("2025-11-20", "BOS", "NYK", 100, 108),
    ("2025-12-05", "NYK", "BOS", 118, 110),
    ("2025-12-15", "BOS", "NYK", 120, 99),
    ("2025-12-31", "SAS", "NYK", 134, 132),
    ("2026-01-02", "NYK", "ATL", 99, 111),
    ("2026-01-03", "NYK", "PHI", 119, 130),
    ("2026-01-05", "DET", "NYK", 121, 90),
    ("2026-01-07", "NYK", "LAC", 123, 111),
    ("2026-01-14", "SAC", "NYK", 112, 101),
    ("2026-01-15", "GSW", "NYK", 126, 113),
    ("2026-01-17", "NYK", "PHX", 99, 106),
    ("2026-01-19", "NYK", "DAL", 97, 114),
    ("2026-01-21", "NYK", "BKN", 120, 66),
    ("2026-02-06", "DET", "NYK", 118, 80),
)

# Observed (home_score - away_score) values for the games with play-by-play margins.
MARGINS = {
    "2025-12-31": (4, -2),
    "2026-01-21": (0, 20, 30),
    "2026-02-06": (38, 20, 3),
}


async def _seed_archive(db_session) -> DatasetRelease:
    release = DatasetRelease(
        version="analyst-operations-test",
        season="2025-26",
        source="test",
        manifest_sha256="c" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    for index, (day, home, away, home_score, away_score) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"operations-{index}",
            season="2025-26",
            game_date=date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type="regular",
            data_status="analysis_ready" if day in MARGINS else "summary_only",
            source_name="test",
            source_game_id=f"operations-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        for sequence, margin in enumerate(MARGINS.get(day, ()), start=1):
            db_session.add(
                GameEvent(
                    game_id=game.id,
                    sequence=sequence,
                    period=1,
                    clock="12:00",
                    event_type="made_shot",
                    description="",
                    home_score=home_score,
                    away_score=away_score - margin,
                    score_margin=margin,
                )
            )
    await db_session.commit()
    return release


async def _deterministic(db_session, question: str):
    release = await _seed_archive(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "operations-test"
    return tools, loop, await loop.run(allow_model=False)


def _claims(result) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for citation in result["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            grouped.setdefault(claim["metric_id"], []).append(claim)
    return grouped


async def test_largest_loss_margin_names_the_worst_defeat(db_session):
    tools, _, result = await _deterministic(db_session, "Who beat the Knicks by the most points?")
    assert tools.scope is not None
    assert tools.scope.operation == "largest_loss_margin"
    claims = _claims(result)["loss_margin"]
    assert [claim["value"] for claim in claims] == [38]
    assert claims[0]["game_ids"] == [
        game.id for game in tools.games if game.game_date == date(2026, 2, 6)
    ]
    answer = result["answer"]
    for expected in ("DET", "118", "80", "38", "2026-02-06"):
        assert expected in answer
    assert result["degraded"] is False
    assert result["warnings"] == []


async def test_largest_win_margin_names_the_best_win(db_session):
    tools, _, result = await _deterministic(db_session, "What was their best win?")
    assert tools.scope is not None
    assert tools.scope.operation == "largest_win_margin"
    claims = _claims(result)["win_margin"]
    assert [claim["value"] for claim in claims] == [54]
    for expected in ("BKN", "120", "66", "54", "2026-01-21"):
        assert expected in result["answer"]
    assert result["degraded"] is False


async def test_longest_losing_streak_returns_every_tied_streak(db_session):
    tools, _, result = await _deterministic(db_session, "When was the longest losing streak?")
    assert tools.scope is not None
    assert tools.scope.operation == "longest_losing_streak"
    claims = _claims(result)["losing_streak"]
    # The archive's longest losing run is the five games from 2025-12-15 to 2026-01-05.
    assert len(claims) == 1
    assert {claim["value"] for claim in claims} == {5}
    # The claim window is the considered population; the run span lives in the statement.
    assert "2025-12-15" in claims[0]["statement"]
    assert _claims(result)["losing_streak_length"][0]["value"] == 5
    answer = result["answer"]
    for expected in ("5", "2025-12-15", "2026-01-05"):
        assert expected in answer
    assert result["degraded"] is False


async def test_streak_scan_is_not_prefiltered_to_losses(db_session):
    """A winning game between two losing runs must break them, not merge them."""
    tools, _, result = await _deterministic(db_session, "When was their longest streak of losses?")
    assert tools.scope is not None
    assert tools.scope.game_result == "L"
    claims = _claims(result)["losing_streak"]
    # Pre-filtering to losses would merge the two runs across the 2026-01-07 win.
    assert {claim["value"] for claim in claims} == {5}


async def test_win_count_matches_the_requested_count_not_scope_totals(db_session):
    tools, _, result = await _deterministic(db_session, "How many games did the Knicks win?")
    assert tools.scope is not None
    assert tools.scope.operation == "win_count"
    assert _claims(result)["wins"][0]["value"] == 5
    assert "losses" not in _claims(result)


async def test_record_keeps_both_outcomes_and_is_not_degraded(db_session):
    tools, _, result = await _deterministic(db_session, "What was the Knicks record this season?")
    assert tools.scope is not None
    assert tools.scope.operation == "team_record"
    claims = _claims(result)
    assert claims["wins"][0]["value"] == 5
    assert claims["losses"][0]["value"] == 10
    assert result["degraded"] is False
    assert result["llm_validated"] is False
    assert result["warnings"] == []


async def test_opponent_record_uses_the_opponent_population(db_session):
    tools, _, result = await _deterministic(db_session, "How did they perform against Boston?")
    assert tools.scope is not None
    assert tools.scope.operation == "team_record"
    claims = _claims(result)
    assert claims["wins"][0]["value"] == 3
    assert claims["losses"][0]["value"] == 1


async def test_opponent_record_paraphrase_resolves_the_same_scope(db_session):
    tools, _, result = await _deterministic(
        db_session, "How have the Knicks done against Boston this season?"
    )
    assert tools.scope is not None
    assert tools.scope.operation == "team_record"
    claims = _claims(result)
    assert claims["wins"][0]["value"] == 3
    assert claims["losses"][0]["value"] == 1


async def test_swing_ranking_uses_observed_range_including_zero(db_session):
    tools, _, result = await _deterministic(db_session, "Which games had the wildest swings?")
    assert tools.scope is not None
    assert tools.scope.operation == "game_swings"
    claims = _claims(result)["score_margin_range"]
    assert claims[0]["value"] == 38
    assert "2026-02-06" in result["answer"]
    # Only event-covered games are ranked; the sweep of no-events games is disclosed.
    ranked_ids = {claim["game_ids"][0] for claim in claims if claim["game_ids"]}
    event_ready = {game.id for game in tools.games if game.game_date.isoformat() in MARGINS}
    assert ranked_ids == event_ready
    assert "3 of 15" in result["answer"] or "3 of 15" in " ".join(result["warnings"])


async def test_undefined_ranking_never_falls_back_to_season_totals(db_session):
    _, loop, result = await _deterministic(db_session, "What was the best comeback of the season?")
    assert "won" not in result["answer"].lower()
    assert _claims(result) == {}
    statuses = {item.status for item in loop.results}
    # A comeback needs a defined run window, so the turn clarifies instead of refusing.
    assert statuses == {"ambiguous_entity"}
    assert result["outcome"] == "clarify" and result["refused"] is False


async def test_prior_turn_ranking_claims_cannot_answer_a_record_question(db_session):
    release = await _seed_archive(db_session)
    loss_tools = AnalystTools(
        db_session, release, "Who beat the Knicks by the most points?", release.season, {}
    )
    await loss_tools.prepare()
    loss_result = await loss_tools.execute(
        ToolCall(name="get_team_stats", question=loss_tools.question, aggregation="total")
    )
    assert {claim.metric_id for claim in loss_result.claims} == {"loss_margin"}

    record_tools = AnalystTools(
        db_session, release, "What was the Knicks record this season?", release.season, {}
    )
    await record_tools.prepare()
    loop = AnalystLoop(record_tools, [])
    loop.results = [loss_result]
    assert loop.fallback_claims() == []


async def test_prior_turn_record_claims_cannot_answer_a_ranking_question(db_session):
    release = await _seed_archive(db_session)
    record_tools = AnalystTools(
        db_session, release, "What was the Knicks record this season?", release.season, {}
    )
    await record_tools.prepare()
    record_result = await record_tools.execute(
        ToolCall(name="get_team_stats", question=record_tools.question, aggregation="total")
    )
    assert {claim.metric_id for claim in record_result.claims} == {"wins", "losses"}

    loss_tools = AnalystTools(
        db_session, release, "Who beat the Knicks by the most points?", release.season, {}
    )
    await loss_tools.prepare()
    loop = AnalystLoop(loss_tools, [])
    loop.results = [record_result]
    assert loop.fallback_claims() == []


async def test_primary_model_unavailability_is_degraded(db_session):
    release = await _seed_archive(db_session)
    tools = AnalystTools(
        db_session, release, "What was the Knicks record this season?", release.season, {}
    )
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    result = await loop.run(allow_model=True)
    assert result["degraded"] is True
    assert result["llm_validated"] is False
    assert result["warnings"]


async def test_state_intent_is_not_persisted(db_session):
    release = await _seed_archive(db_session)
    state = {"intent": "narrative"}
    tools = AnalystTools(
        db_session, release, "What was the Knicks record this season?", release.season, state
    )
    await tools.prepare()
    assert "intent" not in tools.state


async def test_operation_is_typed_on_the_resolved_query(db_session):
    release = await _seed_archive(db_session)
    tools = AnalystTools(
        db_session, release, "Which team beat the Knicks by the biggest margin?", release.season, {}
    )
    await tools.prepare()
    assert tools.scope is not None
    assert tools.scope.operation == "largest_loss_margin"
