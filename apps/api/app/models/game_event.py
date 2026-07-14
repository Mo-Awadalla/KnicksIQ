"""GameEvent ORM model — one row per normalized play-by-play event."""

from __future__ import annotations

from sqlalchemy import Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class GameEvent(Base, TimestampMixin):
    __tablename__ = "game_events"
    __table_args__ = (
        Index("ix_game_events_game_period_seq", "game_id", "period", "sequence"),
        Index("ix_game_events_game_team_type", "game_id", "team_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    clock: Mapped[str] = mapped_column(String(8))

    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(
        Enum(
            "made_shot",
            "missed_shot",
            "rebound",
            "turnover",
            "foul",
            "substitution",
            "timeout",
            "free_throw",
            "jump_ball",
            "period_start",
            "period_end",
            name="event_type",
        ),
        index=True,
    )
    description: Mapped[str] = mapped_column(String(512), default="")

    home_score: Mapped[int] = mapped_column(Integer, default=0)
    away_score: Mapped[int] = mapped_column(Integer, default=0)
    score_margin: Mapped[int] = mapped_column(Integer, default=0)

    shot_type: Mapped[str | None] = mapped_column(
        Enum("2pt", "3pt", "ft", "unknown", name="shot_type"),
        nullable=True,
    )
    shot_result: Mapped[str | None] = mapped_column(
        Enum("made", "missed", name="shot_result"),
        nullable=True,
    )
    shot_distance_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)

    game: Mapped[Game] = relationship(back_populates="events")  # type: ignore[name-defined]  # noqa: F821
    player: Mapped[Player | None] = relationship()  # type: ignore[name-defined]  # noqa: F821

    @property
    def player_name(self) -> str | None:
        return self.player.full_name if self.player else None
