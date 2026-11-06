"""Job queue — thin wrapper around RQ that handles the
database-backed job lifecycle.

The API calls `enqueue_ingest_games(...)` which:
  1. Creates a Job row in the DB (status=queued)
  2. Enqueues an RQ job that runs the actual work and updates the row
  3. Returns the job_id so the API can return 202 Accepted

The API can then poll the Job row directly — no need to talk to Redis
for status, which keeps the read path free of Redis.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.job import Job
from redis import Redis
from rq import Queue
from sqlalchemy import update

from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import create_job

_settings = get_settings()


def _get_queue() -> Queue:
    redis_conn = Redis.from_url(_settings.redis_url, db=_settings.redis_db)
    return Queue(
        _settings.default_queue,
        connection=redis_conn,
        default_timeout=_settings.job_timeout,
    )


async def _enqueue(
    job_type: str, target: str, arguments: dict[str, Any], payload: dict[str, Any]
) -> str:
    job_id = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        await create_job(
            db, job_id=job_id, job_type=job_type, payload=payload, queue=_settings.default_queue
        )
    try:
        await asyncio.to_thread(
            _get_queue().enqueue,
            target,
            kwargs={"job_id": job_id, **arguments},
            job_id=f"{job_type}-{job_id}",
        )
    except Exception as exc:
        # Publication may have succeeded before a transport error. Never overwrite
        # a worker that has already claimed or completed the job.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(
                    status="failed",
                    finished_at=datetime.now(UTC),
                    error_message=f"Queue publication failed: {type(exc).__name__}",
                )
            )
            await db.commit()
        raise
    return job_id


async def enqueue_ingest_games(season: str | None = None, *, include_playoffs: bool = False) -> str:
    arguments = {"season": season, "include_playoffs": include_playoffs}
    return await _enqueue(
        "ingest_games",
        "worker_app.jobs.ingest_games.ingest_games",
        arguments,
        {key: value for key, value in arguments.items() if value is not None},
    )


async def enqueue_ingest_game_detail(game_db_id: int) -> str:
    return await _enqueue(
        "ingest_game_detail",
        "worker_app.jobs.ingest_game_detail.ingest_game_detail",
        {"game_db_id": game_db_id},
        {"game_id": game_db_id},
    )


async def enqueue_detect_runs(game_db_id: int) -> str:
    return await _enqueue(
        "detect_runs",
        "worker_app.jobs.detect_runs.detect_game_features",
        {"game_db_id": game_db_id},
        {"game_id": game_db_id},
    )
