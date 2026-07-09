"""Tests for scoring run detector."""

from __future__ import annotations

from basketball_core.detectors.scoring_run import (
    ScoringRunConfig,
    detect_knicks_runs,
    detect_opponent_runs,
    detect_scoring_runs,
)
from basketball_core.models.event import EventType, GameEvent, ShotResult, ShotType


def make_event(
    seq: int,
    period: int,
    clock: str,
    team_id: str | None,
    event_type: EventType,
    home_score: int = 0,
    away_score: int = 0,
    points: int = 0,
) -> GameEvent:
    shot_type = (
        ShotType.TWO_POINT if points == 2 else (ShotType.THREE_POINT if points == 3 else None)
    )
    shot_result = ShotResult.MADE if points > 0 else None
    return GameEvent(
        game_id=1,
        sequence=seq,
        period=period,
        clock=clock,
        team_id=team_id,
        event_type=event_type,
        home_score=home_score,
        away_score=away_score,
        score_margin=home_score - away_score,
        shot_type=shot_type,
        shot_result=shot_result,
    )


def test_empty_event_list_returns_no_runs():
    assert detect_scoring_runs([]) == []


def test_single_event_no_runs():
    events = [make_event(1, 1, "11:00", "NYK", EventType.MADE_SHOT, points=2)]
    assert detect_scoring_runs(events) == []  # 2-pt alone is below default threshold of 6


def test_detects_knicks_scoring_run():
    """A 8-0 Knicks run that ends when BOS scores should be detected."""
    events = [
        make_event(1, 2, "8:00", "NYK", EventType.MADE_SHOT, points=2, home_score=2),
        make_event(2, 2, "7:40", "NYK", EventType.MADE_SHOT, points=2, home_score=4),
        make_event(3, 2, "7:10", "NYK", EventType.MISSED_SHOT, home_score=4),
        make_event(4, 2, "6:50", "NYK", EventType.MADE_SHOT, points=2, home_score=6),
        make_event(5, 2, "6:30", "NYK", EventType.MADE_SHOT, points=2, home_score=8),
        make_event(6, 2, "6:00", "BOS", EventType.MADE_SHOT, points=2, home_score=8, away_score=2),
    ]
    runs = detect_knicks_runs(events)
    assert len(runs) == 1
    assert runs[0].team_id == "NYK"
    assert runs[0].points_for == 8
    assert runs[0].points_against == 0
    assert runs[0].score_delta == 8
    # Run ends at the last NYK event (6:30), not the BOS terminator (6:00).
    assert runs[0].end_clock == "6:30"
    assert runs[0].start_clock == "8:00"


def test_detects_opponent_scoring_run():
    """A 6-0 opponent run should be detected."""
    events = [
        make_event(1, 3, "9:00", "BOS", EventType.MADE_SHOT, points=2, away_score=2),
        make_event(2, 3, "8:30", "BOS", EventType.MADE_SHOT, points=2, away_score=4),
        make_event(3, 3, "8:00", "BOS", EventType.MADE_SHOT, points=3, away_score=7),
        make_event(4, 3, "7:30", "NYK", EventType.MISSED_SHOT),
    ]
    runs = detect_opponent_runs(events)
    assert len(runs) == 1
    assert runs[0].team_id == "BOS"
    assert runs[0].score_delta == 7
    assert runs[0].points_for == 7


def test_run_closed_by_opponent_score():
    """Once the opponent scores, the Knicks' run is over."""
    events = [
        make_event(1, 4, "5:00", "NYK", EventType.MADE_SHOT, points=2, home_score=2),
        make_event(2, 4, "4:45", "NYK", EventType.MADE_SHOT, points=2, home_score=4),
        make_event(3, 4, "4:30", "NYK", EventType.MADE_SHOT, points=2, home_score=6),
        make_event(4, 4, "4:15", "NYK", EventType.MADE_SHOT, points=2, home_score=8),
        make_event(5, 4, "4:00", "BOS", EventType.MADE_SHOT, points=2, home_score=8, away_score=2),
        make_event(6, 4, "3:30", "NYK", EventType.MADE_SHOT, points=2, home_score=10),
        make_event(7, 4, "3:00", "NYK", EventType.MADE_SHOT, points=2, home_score=12),
    ]
    knicks_runs = detect_knicks_runs(events)
    # Should detect the 8-0 run, NOT extend it through the BOS score
    assert len(knicks_runs) == 1
    assert knicks_runs[0].score_delta == 8
    assert knicks_runs[0].start_clock == "5:00"
    assert knicks_runs[0].end_clock == "4:15"


def test_run_respects_min_threshold():
    """A 4-0 run with default threshold of 6 should NOT be detected."""
    events = [
        make_event(1, 1, "10:00", "NYK", EventType.MADE_SHOT, points=2),
        make_event(2, 1, "9:45", "NYK", EventType.MADE_SHOT, points=2),
        make_event(3, 1, "9:30", "BOS", EventType.MADE_SHOT, points=2),
    ]
    assert detect_knicks_runs(events) == []


def test_custom_threshold():
    """A custom threshold of 4 should detect the 4-0 run."""
    events = [
        make_event(1, 1, "10:00", "NYK", EventType.MADE_SHOT, points=2),
        make_event(2, 1, "9:45", "NYK", EventType.MADE_SHOT, points=2),
        make_event(3, 1, "9:30", "BOS", EventType.MADE_SHOT, points=2),
    ]
    cfg = ScoringRunConfig(min_run_points=4)
    runs = detect_knicks_runs(events, cfg)
    assert len(runs) == 1
    assert runs[0].score_delta == 4
