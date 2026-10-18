"""Player analytics archive coverage, availability and timeframe contracts."""

from __future__ import annotations

import json
from datetime import date

from app.models.game import Game
from app.models.generated_stat_fact import GeneratedStatFact
from app.services.player_analytics import answer_player_question
from app.services.player_intelligence.planning import _parse_plan, _window_limitation
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import select


async def test_last_appearances_exclude_zero_minute_rows_and_keep_receipts(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="What did Jalen Brunson average in his last 2 appearances?",
        season="2025-26",
    )
    assert answer is not None
    payload = answer.analytics
    assert payload["status"] == "complete"
    result = payload["results"][0]
    assert result["type"] == "aggregate"
    assert result["sample_size"] == 2
    assert result["raw_values"]["points"] == 25
    assert len(result["source_game_ids"]) == 2
    assert all(citation["metadata"]["result_id"] == result["id"] for citation in answer.citations)


async def test_common_discovery_window_uses_precomputed_release_catalog(db_session) -> None:
    release, player = await _seed_release_stats(db_session)
    db_session.add(
        GeneratedStatFact(
            release_id=release.id,
            fingerprint="f" * 64,
            fact_type="window_leader",
            player_ids_json=json.dumps([player.nba_player_id]),
            stat_keys_json=json.dumps(["points"]),
            timeframe_json=json.dumps(
                {"kind": "regular_season", "label": "2025-26 regular season"}
            ),
            statement="Jalen Brunson had the catalog's notable scoring line.",
            result_json=json.dumps({"value": 25}),
            source_game_ids_json=json.dumps(["analytics-1", "analytics-3"]),
            sample_size=2,
            total_score=0.75,
            score_components_json=json.dumps({"magnitude": 0.3}),
            detector_version="player-intelligence-v1",
            data_through=date(2026, 1, 3),
        )
    )
    await db_session.commit()
    answer = await answer_player_question(
        db_session,
        question="What was notable about Jalen Brunson's points this regular season?",
        season="2025-26",
    )
    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["type"] == "notable_facts"
    assert result["facts"][0]["fingerprint"] == "f" * 64
    assert len(result["source_game_ids"]) == 2


async def test_invalid_and_word_number_windows_are_typed_without_fallback(db_session) -> None:
    await _seed_release_stats(db_session)
    invalid = await answer_player_question(
        db_session,
        question="What did JB average over his last 0 games?",
        season="2025-26",
    )
    assert invalid is not None
    assert invalid.analytics["status"] == "limited"
    assert invalid.analytics["results"] == []
    assert _window_limitation("last negative five") is not None

    word_number = await answer_player_question(
        db_session,
        question="What did JB average over his last five appearances?",
        season="2025-26",
    )
    assert word_number is not None
    assert word_number.analytics["status"] == "limited"
    assert word_number.analytics["plan"]["timeframe"]["last_n"] == 5


async def test_availability_separates_appearances_from_archive_coverage(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="How many games did Jalen Brunson appear in this season?",
        season="2025-26",
    )
    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["appearances"] == 2
    assert result["requested_team_games"] == 3
    assert answer.analytics["coverage"]["covered_game_count"] == 3
    assert answer.analytics["coverage"]["expected_game_count"] == 3
    assert len(result["source_game_ids"]) == 3


async def test_month_all_star_and_explicit_date_windows_parse_deterministically(db_session) -> None:
    await _seed_release_stats(db_session)
    january = _parse_plan("JB points in January", [])
    assert january.timeframe.start_date == "2026-01-01"
    assert january.timeframe.end_date == "2026-01-31"
    before = _parse_plan("JB points before All-Star", [])
    assert before.timeframe.end_date == "2026-02-11"
    after = _parse_plan("JB points after the All-Star break", [])
    assert after.timeframe.start_date == "2026-02-19"
    explicit = _parse_plan("JB points from 2026-01-01 through 2026-01-03", [])
    assert explicit.timeframe.start_date == "2026-01-01"
    assert explicit.timeframe.end_date == "2026-01-03"


async def test_default_archive_includes_postseason_but_explicit_regular_does_not(db_session):
    release, _ = await _seed_release_stats(db_session)
    game = (
        await db_session.execute(
            select(Game).where(Game.release_id == release.id, Game.nba_game_id == "analytics-3")
        )
    ).scalar_one()
    game.season_type = "playoffs"
    await db_session.commit()
    whole = await answer_player_question(
        db_session, question="What was Jalen Brunson's scoring average?", season="2025-26"
    )
    assert whole is not None
    regular = await answer_player_question(
        db_session,
        question="What was Jalen Brunson's regular-season scoring average?",
        season="2025-26",
    )
    assert regular is not None
    assert whole.analytics["results"][0]["raw_values"]["points"] == 25
    assert whole.analytics["plan"]["timeframe"]["kind"] == "full_archive"
    assert regular.analytics["results"][0]["raw_values"]["points"] == 20
    assert regular.analytics["plan"]["timeframe"]["kind"] == "regular_season"


async def test_last_player_games_exclude_dnp_and_comparison_keeps_each_player_window(db_session):
    await _seed_release_stats(db_session)
    one = await answer_player_question(
        db_session, question="What did Brunson average over his last 2 games?", season="2025-26"
    )
    assert one is not None
    assert one.analytics["plan"]["timeframe"]["unit"] == "appearances"
    assert one.analytics["results"][0]["raw_values"]["points"] == 25
    compare = await answer_player_question(
        db_session,
        question="Compare Brunson and Towns scoring over their last 2 appearances",
        season="2025-26",
    )
    assert compare is not None
    groups = {r["label"]: r for r in compare.analytics["results"][0]["groups"]}
    assert (
        groups["Jalen Brunson"]["sample_size"] == groups["Karl-Anthony Towns"]["sample_size"] == 2
    )
    assert groups["Karl-Anthony Towns"]["raw_values"]["points"] == 17.5
