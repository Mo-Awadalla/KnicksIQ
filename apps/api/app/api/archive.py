"""Public archive release metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.report import Report

router = APIRouter(prefix="/archive", tags=["archive"])

SUPPORTED_CAPABILITIES = [
    "records",
    "scores_and_margins",
    "opponents",
    "player_and_team_box_scores",
    "shooting_splits",
    "quarter_scoring",
    "play_by_play",
    "scoring_runs",
    "reviewed_postgame_reports",
]


class ArchiveStatus(BaseModel):
    season: str
    data_version: str
    games: int = Field(ge=0)
    regular_season_games: int = Field(ge=0)
    postseason_games: int = Field(ge=0)
    reports: int = Field(ge=0)
    activated_at: datetime | None
    capabilities: list[str]


@router.get("/status", response_model=ArchiveStatus)
async def archive_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ArchiveStatus:
    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        if get_settings().test_mode:
            game_filters = [Game.season == get_settings().dataset_season]
            release_id = None
            version = "test-seed"
            activated_at = None
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No validated dataset release is active",
            )
    else:
        game_filters = [Game.release_id == release.id]
        release_id = release.id
        version = release.version
        activated_at = release.activated_at

    totals = (
        await db.execute(
            select(
                func.count(Game.id),
                func.count(Game.id).filter(Game.season_type == "regular"),
                func.count(Game.id).filter(Game.season_type.in_(["play_in", "playoffs"])),
            ).where(*game_filters)
        )
    ).one()
    report_stmt = select(func.count(Report.id)).where(Report.reviewed.is_(True))
    if release_id is not None:
        report_stmt = report_stmt.where(Report.release_id == release_id)
    reports = (await db.execute(report_stmt)).scalar_one()
    return ArchiveStatus(
        season=release.season if release else get_settings().dataset_season,
        data_version=version,
        games=totals[0],
        regular_season_games=totals[1],
        postseason_games=totals[2],
        reports=reports,
        activated_at=activated_at,
        capabilities=SUPPORTED_CAPABILITIES,
    )
