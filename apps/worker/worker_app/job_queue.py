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

import uuid

from redis import Redis
from rq import Queue

from worker_app.core.config import get_settings

_settings = get_settings()


def _get_queue() -> Queue:
    redis_conn = Redis.from_url(_settings.redis_url, db=_settings.redis_db)
    return Queue(
        _settings.default_queue,
        connection=redis_conn,
        default_timeout=_settings.job_timeout,
    )


def enqueue_ingest_games(season: str | None = None) -> str:
    """Enqueue an ingest-games job. Returns the job_id."""
    job_id = uuid.uuid4().hex
    queue = _get_queue()
    queue.enqueue(
        "worker_app.jobs.ingest_games.ingest_games",
        kwargs={"job_id": job_id, "season": season},
        job_id=f"ingest_games-{job_id}",
    )
    return job_id


def enqueue_ingest_game_detail(game_db_id: int) -> str:
    """Enqueue an ingest-game-detail job. Returns the job_id."""
    job_id = uuid.uuid4().hex
    queue = _get_queue()
    queue.enqueue(
        "worker_app.jobs.ingest_game_detail.ingest_game_detail",
        kwargs={"job_id": job_id, "game_db_id": game_db_id},
        job_id=f"ingest_game_detail-{job_id}",
    )
    return job_id


def enqueue_detect_runs(game_db_id: int) -> str:
    """Enqueue a job to run scoring-run + bad-stretch detection on a game."""
    job_id = uuid.uuid4().hex
    queue = _get_queue()
    queue.enqueue(
        "worker_app.jobs.detect_runs.detect_game_features",
        kwargs={"job_id": job_id, "game_db_id": game_db_id},
        job_id=f"detect_runs-{job_id}",
    )
    return job_id
