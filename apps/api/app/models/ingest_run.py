"""Ingest audit records."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IngestRun(Base, TimestampMixin):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    team_id: Mapped[str] = mapped_column(String(8), default="NYK", index=True)
    season: Mapped[str] = mapped_column(String(16), index=True)
    include_playoffs: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
