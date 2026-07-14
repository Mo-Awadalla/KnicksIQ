"""Job management endpoints.

Enqueue work and read job status. The queue uses RQ + Redis under
the hood, but the API reads status from the database (Job rows) so
the read path doesn't depend on Redis.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import require_admin_api_key
from app.core.db import AsyncSessionLocal, get_db
from app.models.job import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


class IngestGamesRequest(BaseModel):
    season: str | None = Field(None, description="Filter to a single season, e.g. '2024-25'")
    include_playoffs: bool = Field(False, description="Audit flag for season cache jobs")


class IngestGameDetailRequest(BaseModel):
    game_id: int = Field(..., description="Internal game id (not the NBA game id)")


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    id: str
    job_type: str
    status: str
    queue: str
    enqueued_by: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    enqueued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    worker_name: str | None


async def _create_job_row(job_id: str, job_type: str, payload: dict[str, Any]) -> None:
    """Insert a Job row in 'queued' state so the API can read status back."""
    async with AsyncSessionLocal() as db:
        job = Job(
            id=job_id,
            job_type=job_type,
            status="queued",
            queue="default",
            payload_json=json.dumps(payload),
        )
        db.add(job)
        await db.commit()


def _serialize(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        queue=job.queue,
        enqueued_by=job.enqueued_by,
        payload=json.loads(job.payload_json or "{}"),
        result=json.loads(job.result_json) if job.result_json else None,
        error_message=job.error_message,
        enqueued_at=job.enqueued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        worker_name=job.worker_name,
    )


@router.post(
    "/ingest/games",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_api_key)],
)
async def trigger_ingest_games(
    body: IngestGamesRequest | None = None,
) -> JobAcceptedResponse:
    """Enqueue a job to ingest games from the data source.

    The actual work is performed by the worker service. The returned
    `job_id` can be polled via `GET /jobs/{job_id}`.
    """
    from worker_app.job_queue import enqueue_ingest_games

    season = body.season if body else None
    include_playoffs = body.include_playoffs if body else False
    job_id = enqueue_ingest_games(season=season)
    payload = {"season": season, "include_playoffs": include_playoffs}
    await _create_job_row(job_id, "ingest_games", {k: v for k, v in payload.items() if v})
    return JobAcceptedResponse(job_id=job_id, status="queued")


@router.post(
    "/ingest/game/{game_id}",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_api_key)],
)
async def trigger_ingest_game_detail(game_id: int) -> JobAcceptedResponse:
    """Enqueue a job to (re)ingest play-by-play events for one game."""
    from worker_app.job_queue import enqueue_ingest_game_detail

    job_id = enqueue_ingest_game_detail(game_db_id=game_id)
    await _create_job_row(job_id, "ingest_game_detail", {"game_id": game_id})
    return JobAcceptedResponse(job_id=job_id, status="queued")


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobStatusResponse:
    """Get the status of a background job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _serialize(job)
