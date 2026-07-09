"""Team schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeamBase(BaseModel):
    id: str
    name: str
    city: str
    abbreviation: str
    conference: str | None = None
    division: str | None = None


class TeamRead(TeamBase):
    model_config = ConfigDict(from_attributes=True)

    nba_team_id: int
