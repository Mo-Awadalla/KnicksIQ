"""Tests for impactful run detector."""

from __future__ import annotations

from basketball_core.detectors.impactful_run import (
    ImpactfulRunConfig,
    detect_impactful_runs,
)
from basketball_core.models.event import EventType, GameEvent, ShotResult, ShotType


def make_event(
    seq: int,
    period: int,
    clock: str,
    team_id: str | None,
    event_type: EventType,
    *,
    points: int = 0,
    home_score: int = 0,
    away_score: int = 0,
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


def test_detects_mixed_net_swing():
    events = [
        make_event(1, 1, "1:30", "NYK", EventType.MADE_SHOT, points=2, home_score=2),
        make_event(2, 1, "1:05", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=3),
        make_event(3, 1, "0:38", "BOS", EventType.MADE_SHOT, points=2, home_score=2, away_score=5),
        make_event(4, 1, "0:04", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=8),
        make_event(5, 2, "11:41", "BOS", EventType.MADE_SHOT, points=2, home_score=2, away_score=10),
        make_event(6, 2, "11:15", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=13),
        make_event(7, 2, "10:42", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=16),
    ]

    runs = detect_impactful_runs(events, ImpactfulRunConfig(home_team_id="NYK", away_team_id="BOS"))

    assert len(runs) == 1
    run = runs[0]
    assert run.team_id == "BOS"
    assert run.points_for == 16
    assert run.points_against == 0
    assert run.score_delta == 16
    assert run.is_highlight is True
    assert "huge_swing" in run.reasons
    assert "16-0" in run.summary


def test_shows_early_8_0_but_does_not_highlight_it():
    events = [
        make_event(1, 1, "11:30", "NYK", EventType.MADE_SHOT, points=2, home_score=2),
        make_event(2, 1, "10:50", "NYK", EventType.MADE_SHOT, points=3, home_score=5),
        make_event(3, 1, "10:10", "NYK", EventType.MADE_SHOT, points=3, home_score=8),
    ]

    runs = detect_impactful_runs(events, ImpactfulRunConfig(home_team_id="NYK", away_team_id="BOS"))

    assert len(runs) == 1
    assert runs[0].score_delta == 8
    assert runs[0].is_highlight is False


def test_clutch_5_0_can_highlight_inside_pressure_zone():
    events = [
        make_event(1, 4, "5:40", "BOS", EventType.MADE_SHOT, points=2, home_score=94, away_score=96),
        make_event(2, 4, "5:10", "BOS", EventType.MADE_SHOT, points=3, home_score=94, away_score=99),
    ]

    runs = detect_impactful_runs(events, ImpactfulRunConfig(home_team_id="NYK", away_team_id="BOS"))

    assert len(runs) == 1
    assert runs[0].score_delta == 5
    assert runs[0].leverage == "clutch"
    assert runs[0].is_highlight is True


def test_late_run_outside_pressure_zone_is_low_leverage():
    events = [
        make_event(1, 4, "5:40", "BOS", EventType.MADE_SHOT, points=3, home_score=80, away_score=98),
        make_event(2, 4, "5:00", "BOS", EventType.MADE_SHOT, points=3, home_score=80, away_score=101),
        make_event(3, 4, "4:30", "BOS", EventType.MADE_SHOT, points=2, home_score=80, away_score=103),
    ]

    runs = detect_impactful_runs(events, ImpactfulRunConfig(home_team_id="NYK", away_team_id="BOS"))

    assert len(runs) == 1
    assert runs[0].leverage == "garbage_time"
    assert runs[0].is_highlight is False


def test_overlapping_candidates_keep_highest_net_swing():
    events = [
        make_event(1, 1, "2:00", "BOS", EventType.MADE_SHOT, points=2, away_score=2),
        make_event(2, 1, "1:35", "BOS", EventType.MADE_SHOT, points=3, away_score=5),
        make_event(3, 1, "1:10", "NYK", EventType.MADE_SHOT, points=2, home_score=2, away_score=5),
        make_event(4, 1, "0:45", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=8),
        make_event(5, 1, "0:20", "BOS", EventType.MADE_SHOT, points=3, home_score=2, away_score=11),
    ]

    runs = detect_impactful_runs(events, ImpactfulRunConfig(home_team_id="NYK", away_team_id="BOS"))

    assert len(runs) == 1
    assert runs[0].points_for == 11
    assert runs[0].points_against == 2
    assert runs[0].score_delta == 9
