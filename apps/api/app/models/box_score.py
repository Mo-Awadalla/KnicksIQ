"""Release-scoped period, team, and player box-score facts."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PeriodScore(Base, TimestampMixin):
    __tablename__ = "period_scores"
    __table_args__ = (
        UniqueConstraint("release_id", "game_id", "team_id", "period"),
        Index("ix_period_scores_game_period", "game_id", "period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("dataset_releases.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    period: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)


class TeamGameStat(Base, TimestampMixin):
    __tablename__ = "team_game_stats"
    __table_args__ = (
        UniqueConstraint("release_id", "game_id", "team_id"),
        Index("ix_team_stats_release_team_game", "release_id", "team_id", "game_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("dataset_releases.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    points: Mapped[int] = mapped_column(Integer)
    field_goals_made: Mapped[int] = mapped_column(Integer, default=0)
    field_goals_attempted: Mapped[int] = mapped_column(Integer, default=0)
    three_pointers_made: Mapped[int] = mapped_column(Integer, default=0)
    three_pointers_attempted: Mapped[int] = mapped_column(Integer, default=0)
    free_throws_made: Mapped[int] = mapped_column(Integer, default=0)
    free_throws_attempted: Mapped[int] = mapped_column(Integer, default=0)
    offensive_rebounds: Mapped[int] = mapped_column(Integer, default=0)
    defensive_rebounds: Mapped[int] = mapped_column(Integer, default=0)
    rebounds: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    steals: Mapped[int] = mapped_column(Integer, default=0)
    blocks: Mapped[int] = mapped_column(Integer, default=0)
    turnovers: Mapped[int] = mapped_column(Integer, default=0)
    personal_fouls: Mapped[int] = mapped_column(Integer, default=0)
    plus_minus: Mapped[int] = mapped_column(Integer, default=0)


class PlayerGameStat(Base, TimestampMixin):
    __tablename__ = "player_game_stats"
    __table_args__ = (
        UniqueConstraint("release_id", "game_id", "player_id"),
        Index("ix_player_stats_release_player_game", "release_id", "player_id", "game_id"),
        Index("ix_player_stats_game_team", "game_id", "team_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("dataset_releases.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    starter: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[str | None] = mapped_column(String(8))
    minutes: Mapped[float] = mapped_column(Float, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    field_goals_made: Mapped[int] = mapped_column(Integer, default=0)
    field_goals_attempted: Mapped[int] = mapped_column(Integer, default=0)
    three_pointers_made: Mapped[int] = mapped_column(Integer, default=0)
    three_pointers_attempted: Mapped[int] = mapped_column(Integer, default=0)
    free_throws_made: Mapped[int] = mapped_column(Integer, default=0)
    free_throws_attempted: Mapped[int] = mapped_column(Integer, default=0)
    offensive_rebounds: Mapped[int] = mapped_column(Integer, default=0)
    defensive_rebounds: Mapped[int] = mapped_column(Integer, default=0)
    rebounds: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    steals: Mapped[int] = mapped_column(Integer, default=0)
    blocks: Mapped[int] = mapped_column(Integer, default=0)
    turnovers: Mapped[int] = mapped_column(Integer, default=0)
    personal_fouls: Mapped[int] = mapped_column(Integer, default=0)
    plus_minus: Mapped[int] = mapped_column(Integer, default=0)
    player: Mapped[Player] = relationship()  # type: ignore[name-defined]  # noqa: F821
