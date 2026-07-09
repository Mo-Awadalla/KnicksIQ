"""Chunk ORM model — a piece of a Document with an optional embedding.

For Phase 5 (mock LLM) we keep the embedding column optional and
populate it via a real embedding model in a later phase. The
retrieval layer in Phase 5 uses simple keyword search; cosine
similarity arrives when we wire a real embedder.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(default=0)
    text: Mapped[str] = mapped_column(Text)
    # Phase 5: text-only retrieval. Phase 5+: vector column.
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    document: Mapped[Document] = relationship(back_populates="chunks")  # type: ignore[name-defined]  # noqa: F821

    @property
    def chunk_metadata(self) -> dict[str, Any]:
        import json

        try:
            return json.loads(self.metadata_json) if self.metadata_json else {}
        except (TypeError, ValueError):
            return {}
