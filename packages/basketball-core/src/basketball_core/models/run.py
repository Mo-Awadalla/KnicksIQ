from __future__ import annotations

from pydantic import BaseModel, Field


class ScoringRun(BaseModel):
    """A sustained scoring run in a game.

    A run is a contiguous span of events where one team outscored the
    other by at least `min_points`. It is bounded when either the
    other team scores or the period ends.
    """

    id: int | None = None
    game_id: int
    team_id: str = Field(..., description="Team that produced the run")
    period: int
    start_sequence: int
    end_sequence: int
    start_clock: str
    end_clock: str
    points_for: int
    points_against: int
    score_delta: int = Field(..., description="points_for - points_against")
    event_count: int
    summary: str = ""

    @property
    def is_opponent_run(self, knicks_team_id: str = "NYK") -> bool:
        return self.team_id != knicks_team_id


class ImpactfulRun(BaseModel):
    """A net scoreboard swing with game-context impact labels."""

    id: int | None = None
    game_id: int
    team_id: str = Field(..., description="Team that benefited from the swing")
    period: int
    end_period: int
    start_sequence: int
    end_sequence: int
    start_clock: str
    end_clock: str
    points_for: int
    points_against: int
    score_delta: int = Field(..., description="points_for - points_against")
    event_count: int
    start_margin: int | None = None
    end_margin: int | None = None
    impact_score: int = 0
    is_highlight: bool = False
    leverage: str = "normal"
    reasons: list[str] = Field(default_factory=list)
    summary: str = ""

    @property
    def is_opponent_run(self, knicks_team_id: str = "NYK") -> bool:
        return self.team_id != knicks_team_id


class BadStretch(BaseModel):
    """A composite bad stretch for the Knicks.

    A bad stretch is identified when the Knicks:
    - Allow an opponent scoring run >= min_run_points
    - Have a field-goal drought >= min_drought_seconds
    - Commit >= min_turnovers turnovers in a short window

    Output is the worst such stretch in a game (or all of them).
    """

    id: int | None = None
    game_id: int
    period: int
    start_clock: str
    end_clock: str
    score_delta: int
    summary: str
    likely_causes: list[str] = Field(default_factory=list)
    knicks_turnovers: int = 0
    knicks_missed_shots: int = 0
    opponent_fast_breaks: int = 0
