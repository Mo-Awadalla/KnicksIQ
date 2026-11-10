"""Tests for query-time RAG routing and evidence quality."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from app.services.possession_chunks import (
    build_possession_chunks,
    expand_neighboring_sequences,
)
from app.services.table_rag import answer_table_question
from app.services.table_rag_games import _dedupe_games
from app.services.table_rag_sandbox import TableRagSandboxError, validate_table_expression
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


def test_and_one_and_multi_free_throw_sequences_are_not_split():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(
                sequence=1,
                clock="2:14",
                team_id="NYK",
                event_type="made_shot",
                description="Brunson makes driving layup",
                home_score=100,
                away_score=98,
            ),
            _event(
                id=2,
                sequence=2,
                clock="2:14",
                team_id="TOR",
                event_type="foul",
                description="Shooting foul; and-one",
                home_score=100,
                away_score=98,
            ),
            _event(
                id=3,
                sequence=3,
                clock="2:14",
                team_id="NYK",
                event_type="free_throw",
                description="Brunson makes free throw 1 of 1",
                home_score=101,
                away_score=98,
            ),
            _event(
                id=4,
                sequence=4,
                clock="1:58",
                team_id="TOR",
                event_type="turnover",
                description="Toronto turnover",
                home_score=101,
                away_score=98,
            ),
        ],
    )

    assert len(chunks) == 2
    assert [row["event_type"] for row in chunks[0].rows] == [
        "made_shot",
        "foul",
        "free_throw",
    ]
    assert chunks[0].metadata["possession_result"] == "free_throws"


def test_offensive_rebound_continues_sequence_and_review_is_honestly_labeled():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(
                sequence=1,
                team_id="NYK",
                event_type="missed_shot",
                description="Brunson misses",
            ),
            _event(
                id=2,
                sequence=2,
                team_id="NYK",
                event_type="rebound",
                description="Knicks offensive rebound",
            ),
            _event(
                id=3,
                sequence=3,
                team_id="NYK",
                event_type="made_shot",
                description="Hart makes putback",
                home_score=2,
            ),
            _event(
                id=4,
                sequence=4,
                team_id=None,
                event_type="timeout",
                description="Replay review overturns basket",
                home_score=0,
            ),
        ],
    )

    assert len(chunks) == 1
    assert len(chunks[0].rows) == 4
    assert chunks[0].metadata["unit_type"] == "event_window"
    assert chunks[0].metadata["possession_result"] is None


def test_missed_free_throw_offensive_rebound_keeps_the_possession_open():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(
                sequence=1, team_id="NYK", event_type="free_throw", description="misses free throw"
            ),
            _event(
                id=2,
                sequence=2,
                team_id="NYK",
                event_type="rebound",
                description="offensive rebound",
            ),
            _event(id=3, sequence=3, team_id="NYK", event_type="made_shot", home_score=2),
        ],
    )
    assert [[row["sequence"] for row in chunk.rows] for chunk in chunks] == [[1, 2, 3]]
    assert chunks[0].metadata["possession_result"] == "made_shot"


def test_period_end_closes_the_current_possession_without_an_orphan_window():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(sequence=1, team_id="NYK", event_type="made_shot", home_score=2),
            _event(id=2, sequence=2, event_type="period_end", clock="0:00", home_score=2),
        ],
    )
    assert [[row["sequence"] for row in chunk.rows] for chunk in chunks] == [[1, 2]]
    assert chunks[0].metadata["end_clock"] == "0:00"


def test_expanded_window_metadata_describes_every_member():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(
                sequence=1,
                team_id="NYK",
                player_id=1,
                player_name="Brunson",
                event_type="made_shot",
            ),
            _event(
                id=2,
                sequence=2,
                team_id="TOR",
                player_id=2,
                player_name="Barnes",
                event_type="turnover",
            ),
        ],
    )
    window = expand_neighboring_sequences([chunks[0]], chunks)[0]
    assert window.metadata["player_ids"] == [1, 2]
    assert window.metadata["player_names"] == ["Barnes", "Brunson"]
    assert window.metadata["team_ids"] == ["NYK", "TOR"]
    assert window.metadata["normalized_event_types"] == ["made_shot", "turnover"]


def test_neighbor_expansion_happens_after_selection_and_merges_overlap():
    chunks = build_possession_chunks(
        _game(),
        [
            _event(sequence=1, team_id="NYK", event_type="turnover"),
            _event(id=2, sequence=2, team_id="TOR", event_type="turnover"),
            _event(id=3, sequence=3, team_id="NYK", event_type="turnover"),
            _event(id=4, sequence=4, team_id="TOR", event_type="turnover"),
        ],
    )

    expanded = expand_neighboring_sequences([chunks[1], chunks[2]], chunks)

    assert len(expanded) == 1
    assert expanded[0].metadata["citation_sequence_ids"] == [chunk.chunk_id for chunk in chunks]
    assert len(expanded[0].rows) == 4


def test_table_rag_sandbox_rejects_imports_and_blocked_modules():
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("__import__('os').system('echo bad')")
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("os.system()")
    with pytest.raises(TableRagSandboxError):
        validate_table_expression("shutil.rmtree()")
    assert validate_table_expression("wins()")


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


def test_possession_evidence_carries_missing_scores_and_preserves_score_corrections():
    events = [
        _event(sequence=1, home_score=25, away_score=22),
        _event(id=2, sequence=2, period=2, home_score=0, away_score=0),
        _event(id=3, sequence=3, period=2, home_score=24, away_score=22),
        _event(id=4, sequence=4, period=2, home_score=0, away_score=0),
    ]
    chunks = build_possession_chunks(_game(), events)
    rows = [row for chunk in chunks for row in chunk.rows]
    assert [(row["home_score"], row["away_score"]) for row in rows] == [
        (25, 22),
        (25, 22),
        (24, 22),
        (24, 22),
    ]
    assert rows[-1]["score_after"] == {"home": 24, "away": 22}
    assert rows[-1]["score_margin"] == 2
    assert events[-1].home_score == 0
