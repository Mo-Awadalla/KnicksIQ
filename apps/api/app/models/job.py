"""Job ORM model — tracks background work for the API to expose status.

Written by the worker; read by the API. The worker runs jobs via
RQ (Redis-backed), but persists high-level status here so the API
can serve `/jobs/{id}` without depending on Redis.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        Enum("queued", "started", "finished", "failed", "cancelled", name="job_status"),
        default="queued",
        index=True,
    )

    queue: Mapped[str] = mapped_column(String(64), default="default")
    enqueued_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    worker_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
