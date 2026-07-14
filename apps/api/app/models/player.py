"""Player ORM model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Player(Base, TimestampMixin):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nba_player_id: Mapped[int] = mapped_column(unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    position: Mapped[str | None] = mapped_column(String(8), nullable=True)
    jersey_number: Mapped[str | None] = mapped_column(String(8), nullable=True)

    team: Mapped[Team | None] = relationship(back_populates="players")  # type: ignore[name-defined]  # noqa: F821
