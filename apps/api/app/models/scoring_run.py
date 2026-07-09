"""ScoringRun ORM model — precomputed scoring runs for fast API reads."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ScoringRun(Base, TimestampMixin):
    __tablename__ = "scoring_runs"
    __table_args__ = (
        Index("ix_scoring_runs_game_period", "game_id", "period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)

    period: Mapped[int] = mapped_column(Integer)
    start_sequence: Mapped[int] = mapped_column(Integer)
    end_sequence: Mapped[int] = mapped_column(Integer)
    start_clock: Mapped[str] = mapped_column(String(8))
    end_clock: Mapped[str] = mapped_column(String(8))

    points_for: Mapped[int] = mapped_column(Integer)
    points_against: Mapped[int] = mapped_column(Integer)
    score_delta: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)

    summary: Mapped[str] = mapped_column(Text, default="")
