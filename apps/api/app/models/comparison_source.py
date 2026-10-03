"""Separate immutable proof for a release's independently verified comparisons."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ComparisonSource(Base, TimestampMixin):
    __tablename__ = "comparison_sources"

    release_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_releases.id", ondelete="CASCADE"), primary_key=True
    )
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_review_sha256: Mapped[str] = mapped_column(String(64))
    trajectories_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    comparison_json: Mapped[str] = mapped_column(Text)
    facts_json: Mapped[str] = mapped_column(Text)
    facts_sha256: Mapped[str] = mapped_column(String(64))
    bindings_json: Mapped[str] = mapped_column(Text)
    bindings_sha256: Mapped[str] = mapped_column(String(64))
