"""Immutable dataset release metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DatasetRelease(Base, TimestampMixin):
    __tablename__ = "dataset_releases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    season: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(128))
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(
        Enum("staged", "active", "superseded", name="dataset_release_status"),
        default="staged",
        index=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
