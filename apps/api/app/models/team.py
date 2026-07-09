"""Team ORM model."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    nba_team_id: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    abbreviation: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    conference: Mapped[str | None] = mapped_column(String(16), nullable=True)
    division: Mapped[str | None] = mapped_column(String(32), nullable=True)

    players: Mapped[list[Player]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="team",
    )
