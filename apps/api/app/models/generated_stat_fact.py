"""Offline-generated, release-scoped structured analytics facts."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GeneratedStatFact(Base, TimestampMixin):
    __tablename__ = "generated_stat_facts"
    __table_args__ = (
        UniqueConstraint("release_id", "fingerprint"),
        Index("ix_generated_facts_release_type_score", "release_id", "fact_type", "total_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("dataset_releases.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    fact_type: Mapped[str] = mapped_column(String(64), index=True)
    player_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    stat_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    timeframe_json: Mapped[str] = mapped_column(Text, default="{}")
    statement: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    source_game_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    sample_size: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[float] = mapped_column(Float)
    score_components_json: Mapped[str] = mapped_column(Text, default="{}")
    detector_version: Mapped[str] = mapped_column(String(64))
    data_through: Mapped[date] = mapped_column(Date)
