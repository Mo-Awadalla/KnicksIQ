"""Game schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.team import TeamRead


class GameSummary(BaseModel):
    """Game representation in list responses (e.g. GET /games)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nba_game_id: str
    season: str
    game_date: date
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: str
    season_type: str = "regular"
    data_status: str = "summary_only"
    source_name: str | None = None
    source_url: str | None = None
    source_game_id: str | None = None
    game_label: str | None = None
    series_name: str | None = None
    series_game_number: int | None = None
    margin: int = Field(..., description="home_score - away_score")
    winner_team_id: str


class GameDetail(GameSummary):
    """Game representation in detail responses (e.g. GET /games/{id})."""

    home_team: TeamRead | None = None
    away_team: TeamRead | None = None


class GameEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    sequence: int
    period: int
    clock: str
    team_id: str | None
    player_id: int | None
    player_name: str | None = None
    event_type: str
    description: str
    home_score: int
    away_score: int
    score_margin: int
    shot_type: str | None
    shot_result: str | None


class ScoringRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    team_id: str
    period: int
    start_clock: str
    end_clock: str
    points_for: int
    points_against: int
    score_delta: int
    event_count: int
    summary: str


class BadStretchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    period: int
    start_clock: str
    end_clock: str
    score_delta: int
    summary: str
    likely_causes: list[str] = Field(default_factory=list)
    knicks_turnovers: int
    knicks_missed_shots: int
    opponent_fast_breaks: int


class PeriodScoreRead(BaseModel):
    period: int
    team_id: str
    points: int


class TeamGameStatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_id: str
    points: int
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    three_pointers_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    offensive_rebounds: int
    defensive_rebounds: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int
    plus_minus: int


class PlayerGameStatRead(TeamGameStatRead):
    player_id: int
    player_name: str
    starter: bool
    position: str | None
    minutes: float


class BoxScoreRead(BaseModel):
    game_id: int
    periods: list[PeriodScoreRead]
    teams: list[TeamGameStatRead]
    players: list[PlayerGameStatRead]
