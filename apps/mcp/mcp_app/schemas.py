"""MCP tool parameter / result schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class GameSummary(BaseModel):
    id: int
    nba_game_id: str
    season: str
    game_date: date
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: str
    margin: int


class GameEventModel(BaseModel):
    sequence: int
    period: int
    clock: str
    team_id: str | None
    player_id: int | None
    event_type: str
    description: str
    home_score: int
    away_score: int
    score_margin: int


class ScoringRunModel(BaseModel):
    team_id: str
    period: int
    start_clock: str
    end_clock: str
    points_for: int
    points_against: int
    score_delta: int
    event_count: int
    summary: str


class BadStretchModel(BaseModel):
    period: int
    start_clock: str
    end_clock: str
    score_delta: int
    summary: str
    likely_causes: list[str]
    knicks_turnovers: int
    knicks_missed_shots: int


class ToolError(BaseModel):
    error: str
    detail: str | None = None
