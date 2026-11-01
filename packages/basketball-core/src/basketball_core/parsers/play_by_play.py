"""Play-by-play parser.

The raw play-by-play feed from the NBA (or any other source) describes
events in vendor-specific strings. This module normalizes them into
the canonical `GameEvent` model used by the rest of the system.

The parser is intentionally a pure function — no I/O, no DB — so it can
be unit-tested with raw event dicts and reused from any service.
"""

from __future__ import annotations

from typing import Any

from basketball_core.models.event import (
    EventType,
    GameEvent,
    ShotResult,
    ShotType,
)

# Map raw event-type strings to canonical event types.
# The mock seed data uses canonical names directly.
_RAW_EVENT_TYPE_MAP: dict[str, EventType] = {
    "FIELD_GOAL_MADE": EventType.MADE_SHOT,
    "FIELD_GOAL_MISSED": EventType.MISSED_SHOT,
    "REBOUND": EventType.REBOUND,
    "TURNOVER": EventType.TURNOVER,
    "FOUL": EventType.FOUL,
    "SUBSTITUTION": EventType.SUBSTITUTION,
    "TIMEOUT": EventType.TIMEOUT,
    "FREE_THROW": EventType.FREE_THROW,
    "JUMP_BALL": EventType.JUMP_BALL,
    "PERIOD_BEGIN": EventType.PERIOD_START,
    "PERIOD_END": EventType.PERIOD_END,
}

# Map raw description tags to canonical event types as a fallback.
_DESCRIPTION_KEYWORDS: list[tuple[str, EventType]] = [
    ("made 3pt", EventType.MADE_SHOT),
    ("made", EventType.MADE_SHOT),
    ("missed 3pt", EventType.MISSED_SHOT),
    ("missed", EventType.MISSED_SHOT),
    ("rebound", EventType.REBOUND),
    ("turnover", EventType.TURNOVER),
    ("foul", EventType.FOUL),
    ("substitution", EventType.SUBSTITUTION),
    ("timeout", EventType.TIMEOUT),
    ("free throw", EventType.FREE_THROW),
]


def normalize_shot_type(text: str) -> ShotType:
    """Infer ShotType from a description string."""
    lower = text.lower()
    if "3pt" in lower or "three" in lower:
        return ShotType.THREE_POINT
    if "free throw" in lower or " ft " in f" {lower} ":
        return ShotType.FREE_THROW
    if "2pt" in lower or "two" in lower:
        return ShotType.TWO_POINT
    return ShotType.UNKNOWN


def infer_event_type(raw: dict[str, Any]) -> EventType:
    """Infer the canonical EventType from a raw event dict."""
    raw_type = str(raw.get("event_type", "")).upper().strip()
    if raw_type in _RAW_EVENT_TYPE_MAP:
        return _RAW_EVENT_TYPE_MAP[raw_type]
    # Canonical name passed directly
    try:
        return EventType(raw_type.lower())
    except ValueError:
        pass
    # Fall back to description keywords
    desc = str(raw.get("description", "")).lower()
    for keyword, etype in _DESCRIPTION_KEYWORDS:
        if keyword in desc:
            return etype
    return EventType.MISSED_SHOT  # safe default — won't fabricate points


def parse_event(game_id: int, sequence: int, raw: dict[str, Any]) -> GameEvent:
    """Parse a single raw event dict into a normalized GameEvent."""
    event_type = infer_event_type(raw)
    desc = str(raw.get("description", ""))
    home_score = int(raw.get("home_score", 0))
    away_score = int(raw.get("away_score", 0))

    shot_type: ShotType | None = None
    shot_result: ShotResult | None = None
    if event_type in (EventType.MADE_SHOT, EventType.MISSED_SHOT, EventType.FREE_THROW):
        shot_type = normalize_shot_type(desc)
        if event_type == EventType.MADE_SHOT or (
            event_type == EventType.FREE_THROW and shot_type == ShotType.FREE_THROW
        ):
            shot_result = ShotResult.MADE
        else:
            shot_result = ShotResult.MISSED
        if event_type == EventType.FREE_THROW:
            shot_type = ShotType.FREE_THROW

    return GameEvent(
        game_id=game_id,
        sequence=sequence,
        period=int(raw.get("period", 1)),
        clock=str(raw.get("clock", "12:00")),
        team_id=raw.get("team_id"),
        player_id=raw.get("player_id"),
        event_type=event_type,
        description=desc,
        home_score=home_score,
        away_score=away_score,
        score_margin=home_score - away_score,
        shot_type=shot_type,
        shot_result=shot_result,
        shot_distance_ft=raw.get("shot_distance_ft"),
    )


def parse_events(game_id: int, raw_events: list[dict[str, Any]]) -> list[GameEvent]:
    """Parse a list of raw event dicts into normalized GameEvents.

    Sequences are reassigned 1..N in input order to guarantee a
    contiguous ordering for the detectors.
    """
    return [parse_event(game_id, i + 1, raw) for i, raw in enumerate(raw_events)]
