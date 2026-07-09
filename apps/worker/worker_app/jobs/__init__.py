"""Job data access — read/write Job rows for the API to surface status.

The worker mutates Job rows; the API reads them. Both use the same
SQLAlchemy models and database connection.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.models.job import Job
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def create_job(
    db: AsyncSession,
    *,
    job_id: str,
    job_type: str,
    payload: dict[str, Any],
    queue: str = "default",
    enqueued_by: str | None = None,
) -> Job:
    job = Job(
        id=job_id,
        job_type=job_type,
        status="queued",
        queue=queue,
        enqueued_by=enqueued_by,
        payload_json=json.dumps(payload),
    )
    db.add(job)
    await db.commit()
    return job


async def get_job(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def mark_started(db: AsyncSession, job_id: str, worker_name: str) -> None:
    job = await get_job(db, job_id)
    if not job:
        return
    job.status = "started"
    job.started_at = datetime.now(UTC)
    job.worker_name = worker_name
    await db.commit()


async def mark_finished(db: AsyncSession, job_id: str, result: dict[str, Any]) -> None:
    job = await get_job(db, job_id)
    if not job:
        return
    job.status = "finished"
    job.finished_at = datetime.now(UTC)
    job.result_json = json.dumps(result, default=str)
    await db.commit()


async def mark_failed(db: AsyncSession, job_id: str, error: str) -> None:
    job = await get_job(db, job_id)
    if not job:
        return
    job.status = "failed"
    job.finished_at = datetime.now(UTC)
    job.error_message = error
    await db.commit()
