"""Player-related endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.player import Player
from app.schemas.player import PlayerRead

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=list[PlayerRead])
async def list_players(
    db: Annotated[AsyncSession, Depends(get_db)],
    team_id: str | None = Query(None, description="Filter by team abbreviation"),
    search: str | None = Query(None, description="Search by name (case-insensitive)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PlayerRead]:
    stmt = select(Player)
    if team_id:
        stmt = stmt.where(Player.team_id == team_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Player.full_name.ilike(like))
    stmt = stmt.order_by(Player.full_name).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return [PlayerRead.model_validate(p) for p in result.scalars().all()]


@router.get("/{player_id}", response_model=PlayerRead)
async def get_player(
    player_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlayerRead:
    player = await db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return PlayerRead.model_validate(player)
