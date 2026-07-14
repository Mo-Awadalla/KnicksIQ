"""Tests for the bad stretch detector."""

from __future__ import annotations

from basketball_core.detectors.bad_stretch import (
    BadStretchConfig,
    detect_bad_stretches,
)
from basketball_core.models.event import EventType, GameEvent, ShotResult, ShotType


def make_event(
    seq: int,
    period: int,
    clock: str,
    team_id: str | None,
    event_type: EventType,
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
        shot_type=shot_type,
        shot_result=shot_result,
    )


def test_empty_events_returns_no_stretches():
    assert detect_bad_stretches([]) == []


def test_detects_dry_spell_as_bad_stretch():
    """A 3+ minute dry spell should be flagged as a bad stretch (drought cause)."""
    events = [
        make_event(1, 2, "8:00", "NYK", EventType.MADE_SHOT, points=2),
        # 3+ minutes of nothing from NYK
        make_event(2, 2, "7:30", "BOS", EventType.MADE_SHOT, points=2),
        make_event(3, 2, "7:00", "BOS", EventType.MADE_SHOT, points=2),
        make_event(4, 2, "6:30", "BOS", EventType.MADE_SHOT, points=2),
        make_event(5, 2, "6:00", "BOS", EventType.MADE_SHOT, points=2),
        make_event(6, 2, "5:30", "BOS", EventType.MADE_SHOT, points=2),
        make_event(7, 2, "5:00", "BOS", EventType.MADE_SHOT, points=2),
    ]
    stretches = detect_bad_stretches(events)
    assert len(stretches) >= 1
    causes = stretches[0].likely_causes
    assert "opponent scoring run" in causes or "offensive drought" in causes


def test_detects_turnover_cluster():
    """Turnovers are causes when they occur inside an opponent impactful run."""
    events = [
        make_event(1, 3, "9:00", "NYK", EventType.MADE_SHOT, points=2),
        make_event(2, 3, "8:30", "NYK", EventType.TURNOVER),
        make_event(3, 3, "8:00", "NYK", EventType.TURNOVER),
        make_event(4, 3, "7:30", "BOS", EventType.MADE_SHOT, points=3),
        make_event(5, 3, "7:00", "BOS", EventType.MADE_SHOT, points=3),
        make_event(6, 3, "6:30", "BOS", EventType.MADE_SHOT, points=2),
    ]
    stretches = detect_bad_stretches(events)
    assert len(stretches) >= 1
    assert any(any("turnovers" in c for c in stretch.likely_causes) for stretch in stretches)


def test_stretch_summary_includes_numbers():
    """The summary should mention the point swing and turnover count."""
    events = [
        make_event(1, 4, "5:00", "NYK", EventType.MADE_SHOT, points=2),
        make_event(2, 4, "4:30", "NYK", EventType.TURNOVER),
        make_event(3, 4, "4:00", "BOS", EventType.MADE_SHOT, points=3),
        make_event(4, 4, "3:30", "BOS", EventType.MADE_SHOT, points=3),
        make_event(5, 4, "3:00", "BOS", EventType.MADE_SHOT, points=2),
    ]
    stretches = detect_bad_stretches(events)
    assert len(stretches) >= 1
    assert stretches[0].summary
    assert stretches[0].score_delta < 0  # negative = Knicks got outscored


def test_detects_game_changing_cross_quarter_swing():
    """A significant opponent swing can bridge quarter boundaries."""
    events = [
        make_event(1, 1, "1:30", "NYK", EventType.MADE_SHOT, points=2),
        make_event(2, 1, "1:05", "BOS", EventType.MADE_SHOT, points=3),
        make_event(3, 1, "0:38", "BOS", EventType.MADE_SHOT, points=2),
        make_event(4, 1, "0:04", "BOS", EventType.MADE_SHOT, points=3),
        make_event(5, 2, "11:41", "BOS", EventType.MADE_SHOT, points=2),
        make_event(6, 2, "11:15", "BOS", EventType.MADE_SHOT, points=3),
        make_event(7, 2, "10:42", "BOS", EventType.MADE_SHOT, points=3),
    ]

    stretches = detect_bad_stretches(events)

    assert stretches
    stretch = stretches[0]
    assert stretch.period == 1
    assert stretch.start_clock == "1:05"
    assert stretch.end_clock == "10:42"
    assert stretch.score_delta == -16
    assert "opponent scoring swing" in stretch.likely_causes
    assert "16-0" in stretch.summary


def test_collapses_repetitive_quarter_boundary_windows():
    """Boundary/noise events should not produce repetitive near-identical stretches."""
    events = [
        make_event(1, 1, "0:22", "BOS", EventType.MADE_SHOT, points=3),
        make_event(2, 1, "0:01", "NYK", EventType.MISSED_SHOT),
        make_event(3, 1, "0:00", None, EventType.PERIOD_END),
        make_event(4, 2, "12:00", None, EventType.PERIOD_START),
        make_event(5, 2, "11:35", "BOS", EventType.MADE_SHOT, points=2),
        make_event(6, 2, "11:02", "NYK", EventType.TURNOVER),
        make_event(7, 2, "10:36", "BOS", EventType.MADE_SHOT, points=3),
        make_event(8, 2, "10:12", "NYK", EventType.MISSED_SHOT),
        make_event(9, 2, "9:42", "BOS", EventType.MADE_SHOT, points=3),
        make_event(10, 2, "8:29", "NYK", EventType.MISSED_SHOT),
    ]

    stretches = detect_bad_stretches(
        events,
        BadStretchConfig(window_seconds=4 * 60, min_swing_points=8),
    )

    assert len(stretches) == 1
    stretch = stretches[0]
    assert stretch.start_clock == "0:22"
    assert stretch.end_clock == "9:42"
    assert "00:00" not in stretch.summary
