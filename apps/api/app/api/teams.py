"""Team-related endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.team import Team
from app.schemas.team import TeamRead

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamRead])
async def list_teams(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TeamRead]:
    result = await db.execute(select(Team).order_by(Team.city))
    return [TeamRead.model_validate(t) for t in result.scalars().all()]


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamRead:
    team = await db.get(Team, team_id)
    return TeamRead.model_validate(team)
