"""Tests for query-time RAG routing and evidence quality."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from app.services.possession_chunks import build_possession_chunks
from app.services.query_classifier import classify_query
from app.services.rag import build_metadata_filters, search_possession_chunks
from app.services.table_rag import (
    TABLE_RAG_TIMEOUT_SECONDS,
    TableRagSandboxError,
    _dedupe_games,
    answer_table_question,
    validate_table_expression,
)
from sqlalchemy import text


def _game() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        game_date=date(2025, 10, 22),
        season="2025-26",
        home_team_id="NYK",
        away_team_id="TOR",
        season_type="regular",
        data_status="events_ready",
        source_name="seed",
        source_url=None,
    )


def _game_row(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "game_date": date(2026, 4, 3),
        "home_team_id": "NYK",
        "away_team_id": "CHI",
        "home_score": 136,
        "away_score": 96,
        "data_status": "summary_only",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _event(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "game_id": 1,
        "sequence": 1,
        "period": 1,
        "clock": "12:00",
        "team_id": None,
        "player_id": None,
        "player_name": None,
        "event_type": "period_start",
        "description": "",
        "home_score": 0,
        "away_score": 0,
        "score_margin": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_classifier_routes_core_query_types():
    assert classify_query("What was the Knicks average score?").is_aggregative is True
    assert classify_query("Compare Knicks vs Boston").kind == "comparative"
    assert classify_query("What happened in Q4 after the timeout?").kind == "temporal"
    assert classify_query("How did the lineup with Brunson do?").kind == "lineup_conditioned"
    assert classify_query("What if the Knicks made two more threes?").kind == "counterfactual"


def test_possession_chunking_respects_period_and_possession_boundaries():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(sequence=1, period=1, clock="12:00", event_type="period_start"),
            _event(
                id=2,
                sequence=2,
                period=1,
                clock="11:40",
                team_id="NYK",
                event_type="missed_shot",
                description="Jalen Brunson misses 3PT",
                player_name="Jalen Brunson",
                player_id=1,
            ),
            _event(
                id=3,
                sequence=3,
                period=1,
                clock="11:36",
                team_id="TOR",
                event_type="rebound",
                description="Toronto defensive rebound",
            ),
            _event(id=4, sequence=4, period=2, clock="12:00", event_type="period_start"),
            _event(
                id=5,
                sequence=5,
                period=2,
                clock="11:50",
                team_id="NYK",
                event_type="made_shot",
                description="Jalen Brunson makes 2PT",
                player_name="Jalen Brunson",
                player_id=1,
                home_score=2,
            ),
        ],
    )
    assert len(chunks) == 2
    assert chunks[0].metadata["end_clock"] == "11:36"
    assert chunks[1].metadata["start_period"] == 2
    assert chunks[1].metadata["player_names"] == ["Jalen Brunson"]


def test_metadata_filter_extraction():
    filters = build_metadata_filters("Show Knicks Q4 possessions vs TOR on 2025-10-22")
    assert filters.dates == {"2025-10-22"}
    assert {"NYK", "TOR"} <= filters.team_ids
    assert filters.periods == {4}


def test_metadata_filter_resolves_full_opponent_name():
    filters = build_metadata_filters("What happened in the Knicks game against Toronto?")
    assert filters.team_ids == {"NYK", "TOR"}


async def test_full_opponent_name_excludes_unrelated_possession_receipts(db_session):
    chunks, _filters = await search_possession_chunks(
        db_session,
        "What happened in the Knicks game against Toronto?",
        limit=10,
    )

    assert chunks
    assert all(
        "TOR"
        in {
            chunk.metadata["home_team_id"],
            chunk.metadata["away_team_id"],
        }
        for chunk in chunks
    )


def test_table_rag_sandbox_rejects_imports_and_blocked_modules():
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("__import__('os').system('echo bad')")
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("os.system()")
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("shutil.rmtree()")
    assert validate_table_expression("wins()")


def test_table_rag_timeout_is_1_5_seconds():
    assert TABLE_RAG_TIMEOUT_SECONDS == 1.5


def test_table_rag_dedupes_seed_and_source_rows_preferring_event_ready():
    rows = [
        _game_row(id=1, data_status="summary_only"),
        _game_row(id=2, data_status="events_ready"),
        _game_row(
            id=3,
            game_date=date(2026, 4, 6),
            home_team_id="ATL",
            away_team_id="NYK",
            home_score=105,
            away_score=108,
            data_status="summary_only",
        ),
    ]
    deduped = _dedupe_games(rows)
    assert [row.id for row in deduped] == [2, 3]


async def test_table_rag_answers_aggregate_from_cached_rows(db_session):
    result = await answer_table_question(
        db_session,
        "What is the Knicks record?",
        season="2025-26",
    )
    assert "NYK is" in result.answer
    assert result.evidence


async def test_table_rag_does_not_mutate_source_tables(db_session):
    before = (
        await db_session.execute(
            text(
                "select "
                "(select count(*) from games), "
                "(select count(*) from game_events), "
                "(select count(*) from players)"
            )
        )
    ).one()
    await answer_table_question(db_session, "How many total points?", season="2025-26")
    after = (
        await db_session.execute(
            text(
                "select "
                "(select count(*) from games), "
                "(select count(*) from game_events), "
                "(select count(*) from players)"
            )
        )
    ).one()
    assert after == before


async def test_possession_search_applies_date_filter_before_retrieval(db_session):
    chunks, filters = await search_possession_chunks(
        db_session,
        "Show Knicks possessions on 2099-01-01",
        season="2025-26",
    )
    assert filters.dates == {"2099-01-01"}
    assert chunks == []
