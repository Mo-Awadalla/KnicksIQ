"""Document ORM model — coarse-grained source material for RAG.

A document is a piece of context the LLM can cite. Examples:
- a game recap
- a generated game summary
- a user-written note

Documents are chunked before being embedded; chunks carry the
actual vector and source metadata.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("release_id", "source_type", "game_id", "title"),
        Index("ix_documents_release_source_game", "release_id", "source_type", "game_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_releases.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(32), index=True
    )  # e.g. 'play_by_play', 'game_summary', 'recap', 'user_note'
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="document",
        cascade="all, delete-orphan",
    )
