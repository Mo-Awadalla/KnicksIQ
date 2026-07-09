"""Game ORM model."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Game(Base, TimestampMixin):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nba_game_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    season: Mapped[str] = mapped_column(String(16), index=True)
    game_date: Mapped[date] = mapped_column(Date, index=True)

    home_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)

    home_score: Mapped[int] = mapped_column(Integer, default=0)
    away_score: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(
        Enum("scheduled", "live", "final", "postponed", name="game_status"),
        default="scheduled",
        index=True,
    )
    season_type: Mapped[str] = mapped_column(
        Enum("regular", "play_in", "playoffs", name="season_type"),
        default="regular",
        index=True,
    )
    data_status: Mapped[str] = mapped_column(
        Enum("summary_only", "events_ready", "analysis_ready", name="game_data_status"),
        default="summary_only",
        index=True,
    )
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_game_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    game_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    series_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    series_game_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])  # type: ignore[name-defined]  # noqa: F821
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])  # type: ignore[name-defined]  # noqa: F821
    events: Mapped[list[GameEvent]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="game",
        cascade="all, delete-orphan",
        order_by="GameEvent.sequence",
    )
