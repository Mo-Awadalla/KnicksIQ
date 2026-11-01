"""Tests for the play-by-play parser."""

from __future__ import annotations

from basketball_core.models.event import EventType, ShotType
from basketball_core.parsers.play_by_play import parse_event, parse_events


def test_parses_canonical_event_type():
    raw = {
        "event_type": "made_shot",
        "description": "Brunson made 2pt jumper",
        "period": 1,
        "clock": "11:30",
        "team_id": "NYK",
        "home_score": 2,
        "away_score": 0,
    }
    ev = parse_event(game_id=1, sequence=1, raw=raw)
    assert ev.event_type == EventType.MADE_SHOT
    assert ev.shot_type == ShotType.TWO_POINT
    assert ev.team_id == "NYK"


def test_parses_three_pointer():
    raw = {
        "event_type": "FIELD_GOAL_MADE",
        "description": "DiVincenzo made 3pt shot",
        "period": 2,
        "clock": "6:15",
        "team_id": "NYK",
        "home_score": 50,
        "away_score": 48,
    }
    ev = parse_event(game_id=1, sequence=2, raw=raw)
    assert ev.event_type == EventType.MADE_SHOT
    assert ev.shot_type == ShotType.THREE_POINT
    assert ev.score_margin == 2


def test_parses_turnover_from_description():
    raw = {
        "event_type": "unknown_thing",
        "description": "Brunson turnover (bad pass)",
        "period": 3,
        "clock": "4:00",
        "team_id": "NYK",
    }
    ev = parse_event(game_id=1, sequence=3, raw=raw)
    assert ev.event_type == EventType.TURNOVER


def test_parses_free_throw():
    raw = {
        "event_type": "FREE_THROW",
        "description": "Randle made free throw 1 of 2",
        "period": 4,
        "clock": "0:30",
        "team_id": "NYK",
    }
    ev = parse_event(game_id=1, sequence=4, raw=raw)
    assert ev.event_type == EventType.FREE_THROW
    assert ev.shot_type == ShotType.FREE_THROW


def test_parse_events_assigns_sequences():
    raw = [
        {
            "event_type": "made_shot",
            "description": "made 2pt",
            "period": 1,
            "clock": "11:00",
            "team_id": "NYK",
        },  # noqa: E501
        {
            "event_type": "made_shot",
            "description": "made 2pt",
            "period": 1,
            "clock": "10:30",
            "team_id": "BOS",
        },  # noqa: E501
        {
            "event_type": "turnover",
            "description": "TO",
            "period": 1,
            "clock": "10:00",
            "team_id": "NYK",
        },  # noqa: E501
    ]
    events = parse_events(game_id=42, raw_events=raw)
    assert len(events) == 3
    assert [e.sequence for e in events] == [1, 2, 3]
    assert all(e.game_id == 42 for e in events)


def test_score_margin_computed_correctly():
    raw = {
        "event_type": "made_shot",
        "description": "made 3pt",
        "period": 1,
        "clock": "8:00",
        "team_id": "NYK",
        "home_score": 70,
        "away_score": 65,
    }
    ev = parse_event(game_id=1, sequence=5, raw=raw)
    assert ev.score_margin == 5  # NYK is home, so home - away
