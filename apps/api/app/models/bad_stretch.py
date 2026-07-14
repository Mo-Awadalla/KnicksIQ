"""BadStretch ORM model — composite bad-stretch detections."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BadStretch(Base, TimestampMixin):
    __tablename__ = "bad_stretches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)

    period: Mapped[int] = mapped_column(Integer)
    start_clock: Mapped[str] = mapped_column(String(8))
    end_clock: Mapped[str] = mapped_column(String(8))

    score_delta: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text, default="")
    likely_causes: Mapped[str] = mapped_column(Text, default="")  # JSON list

    knicks_turnovers: Mapped[int] = mapped_column(Integer, default=0)
    knicks_missed_shots: Mapped[int] = mapped_column(Integer, default=0)
    opponent_fast_breaks: Mapped[int] = mapped_column(Integer, default=0)
