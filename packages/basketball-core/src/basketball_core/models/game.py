from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TeamSide(str, Enum):
    HOME = "home"
    AWAY = "away"


class Team(BaseModel):
    id: str = Field(..., description="Internal team id (e.g. 'NYK')")
    nba_team_id: int
    name: str
    city: str
    abbreviation: str
    conference: str | None = None
    division: str | None = None


class GameStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"


class Game(BaseModel):
    id: int | None = None
    nba_game_id: str
    season: str
    game_date: date
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: GameStatus = GameStatus.SCHEDULED

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def winner_team_id(self) -> str:
        return self.home_team_id if self.home_score > self.away_score else self.away_team_id

    def is_knicks_game(self, knicks_team_id: str = "NYK") -> bool:
        return self.home_team_id == knicks_team_id or self.away_team_id == knicks_team_id

    def knicks_side(self, knicks_team_id: str = "NYK") -> TeamSide | None:
        if self.home_team_id == knicks_team_id:
            return TeamSide.HOME
        if self.away_team_id == knicks_team_id:
            return TeamSide.AWAY
        return None

    def knicks_score(self, knicks_team_id: str = "NYK") -> int:
        side = self.knicks_side(knicks_team_id)
        if side == TeamSide.HOME:
            return self.home_score
        if side == TeamSide.AWAY:
            return self.away_score
        return 0

    def opponent_score(self, knicks_team_id: str = "NYK") -> int:
        side = self.knicks_side(knicks_team_id)
        if side == TeamSide.HOME:
            return self.away_score
        if side == TeamSide.AWAY:
            return self.home_score
        return 0
