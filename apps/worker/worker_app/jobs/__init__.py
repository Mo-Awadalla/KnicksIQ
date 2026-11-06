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


async def _job_in_state(db: AsyncSession, job_id: str, expected: str) -> Job:
    job = (
        await db.execute(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None or job.status != expected:
        actual = job.status if job else "unregistered"
        raise ValueError(f"Job {job_id} must be {expected}, not {actual}")
    return job


async def mark_started(db: AsyncSession, job_id: str, worker_name: str) -> None:
    job = await _job_in_state(db, job_id, "queued")
    job.status = "started"
    job.started_at = datetime.now(UTC)
    job.worker_name = worker_name
    job.finished_at = None
    job.result_json = None
    job.error_message = None
    await db.commit()


async def mark_finished(db: AsyncSession, job_id: str, result: dict[str, Any]) -> None:
    job = await _job_in_state(db, job_id, "started")
    job.status = "finished"
    job.finished_at = datetime.now(UTC)
    job.result_json = json.dumps(result, default=str)
    await db.commit()


async def mark_failed(db: AsyncSession, job_id: str, error: str) -> None:
    job = await _job_in_state(db, job_id, "started")
    job.status = "failed"
    job.finished_at = datetime.now(UTC)
    job.error_message = error
    await db.commit()
