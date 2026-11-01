from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Normalized play-by-play event types.

    The raw NBA feed uses many granular types (e.g. "Made Field Goal",
    "Missed 3pt", "Offensive Foul"). The parser collapses these into
    the canonical set below so detectors and the report layer can
    reason about the game in stable terms.
    """

    MADE_SHOT = "made_shot"
    MISSED_SHOT = "missed_shot"
    REBOUND = "rebound"
    TURNOVER = "turnover"
    FOUL = "foul"
    SUBSTITUTION = "substitution"
    TIMEOUT = "timeout"
    FREE_THROW = "free_throw"
    JUMP_BALL = "jump_ball"
    PERIOD_START = "period_start"
    PERIOD_END = "period_end"


class ShotResult(str, Enum):
    MADE = "made"
    MISSED = "missed"


class ShotType(str, Enum):
    TWO_POINT = "2pt"
    THREE_POINT = "3pt"
    FREE_THROW = "ft"
    UNKNOWN = "unknown"


class GameEvent(BaseModel):
    """A single normalized play-by-play event."""

    id: int | None = None
    game_id: int
    sequence: int = Field(..., description="Order within the game (1-indexed)")
    period: int = Field(..., ge=1, le=14, description="Regulation or overtime period")
    clock: str = Field(..., description="Period clock, e.g. '8:41'")
    team_id: str | None = Field(None, description="Team that caused the event (None for neutral)")
    player_id: int | None = None
    event_type: EventType
    description: str = ""

    # Score state after the event
    home_score: int = 0
    away_score: int = 0
    score_margin: int = 0  # home - away

    # Shot metadata (only set for shot / FT events)
    shot_type: ShotType | None = None
    shot_result: ShotResult | None = None
    shot_distance_ft: int | None = None

    @property
    def is_scoring_event(self) -> bool:
        if self.event_type in (EventType.MADE_SHOT, EventType.FREE_THROW):
            return self.shot_result == ShotResult.MADE
        return False

    @property
    def points_scored(self) -> int:
        if not self.is_scoring_event:
            return 0
        if self.shot_type == ShotType.THREE_POINT:
            return 3
        if self.shot_type == ShotType.TWO_POINT:
            return 2
        if self.shot_type == ShotType.FREE_THROW:
            return 1
        return 0
