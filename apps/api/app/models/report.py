"""Report ORM model — generated postgame reports.

A report is a structured artifact built by the report generator
service. It contains the LLM output (or mock output) plus the
tool-call trace and source citations, so the report can be audited
end-to-end.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (
        Index(
            "uq_reports_release_game_type_idx",
            "release_id",
            "game_id",
            "report_type",
            unique=True,
        ),
        Index("ix_reports_release_game", "release_id", "game_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_releases.id"), nullable=True, index=True
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    report_type: Mapped[str] = mapped_column(String(64), default="postgame")
    title: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(Text, default="")
    turning_point: Mapped[str] = mapped_column(Text, default="")
    best_stretch: Mapped[str] = mapped_column(Text, default="")
    worst_stretch: Mapped[str] = mapped_column(Text, default="")
    player_notes: Mapped[str] = mapped_column(Text, default="[]")
    suggested_adjustments: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_trace_json: Mapped[str] = mapped_column(Text, default="[]")
