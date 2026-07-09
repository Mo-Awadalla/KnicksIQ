"""Report endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import require_admin_api_key
from app.core.db import get_db
from app.models.report import Report

router = APIRouter(prefix="/reports", tags=["reports"])


class PostgameRequest(BaseModel):
    game_id: int = Field(..., description="Internal game id to generate a report for")
    include_tool_trace: bool = True
    include_sources: bool = True


class PostgameResponse(BaseModel):
    id: int
    game_id: int
    title: str
    summary: str
    turning_point: str
    best_stretch: str
    worst_stretch: str
    player_notes: list[str]
    suggested_adjustments: list[str]
    sources: list[Any]
    tool_calls: list[dict[str, Any]]
    created_at: datetime


class ReportSummary(BaseModel):
    id: int
    game_id: int
    title: str
    summary: str
    created_at: datetime


@router.post(
    "/postgame",
    response_model=PostgameResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_api_key)],
)
async def generate_postgame(req: PostgameRequest) -> PostgameResponse:
    """Synchronously generate a postgame report for a game.

    In a heavier setup this would be a queued job; for Phase 5 we
    run it inline. The 201 status signals a resource was created
    (the Report row).
    """
    from app.services.report_generator import generate_postgame_report

    try:
        result = await generate_postgame_report(game_id=req.game_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if not req.include_tool_trace:
        result["tool_calls"] = []
    if not req.include_sources:
        result["sources"] = []
    return PostgameResponse(**result)


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    db: Annotated[AsyncSession, Depends(get_db)],
    game_id: int | None = None,
    limit: int = 50,
) -> list[ReportSummary]:
    stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if game_id is not None:
        stmt = stmt.where(Report.game_id == game_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        ReportSummary(
            id=r.id,
            game_id=r.game_id,
            title=r.title,
            summary=r.summary,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{report_id}", response_model=PostgameResponse)
async def get_report(
    report_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostgameResponse:
    row = await db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return PostgameResponse(
        id=row.id,
        game_id=row.game_id,
        title=row.title,
        summary=row.summary,
        turning_point=row.turning_point,
        best_stretch=row.best_stretch,
        worst_stretch=row.worst_stretch,
        player_notes=json.loads(row.player_notes or "[]"),
        suggested_adjustments=json.loads(row.suggested_adjustments or "[]"),
        sources=json.loads(row.sources_json or "[]"),
        tool_calls=[],
        created_at=row.created_at,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    _admin: Annotated[None, Depends(require_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    row = await db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    await db.delete(row)
    await db.commit()
