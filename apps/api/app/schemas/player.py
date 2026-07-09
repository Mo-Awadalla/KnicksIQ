"""Player schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlayerBase(BaseModel):
    full_name: str
    position: str | None = None
    jersey_number: str | None = None


class PlayerRead(PlayerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nba_player_id: int
    team_id: str | None = None
