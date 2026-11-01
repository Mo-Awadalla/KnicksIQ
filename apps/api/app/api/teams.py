"""Team-related endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.team import Team
from app.schemas.team import TeamRead
from app.services.releases import restrict_teams_to_active_release

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamRead])
async def list_teams(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TeamRead]:
    result = await db.execute(restrict_teams_to_active_release(select(Team).order_by(Team.city)))
    return [TeamRead.model_validate(t) for t in result.scalars().all()]


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamRead:
    team = (
        await db.execute(restrict_teams_to_active_release(select(Team).where(Team.id == team_id)))
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return TeamRead.model_validate(team)
