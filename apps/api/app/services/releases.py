"""Reusable active-release filtering for public reads."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from sqlalchemy import select


def restrict_to_active_release(stmt: Any) -> Any:
    if not get_settings().is_production:
        return stmt
    active_release = (
        select(DatasetRelease.id)
        .where(
            DatasetRelease.status == "active",
            DatasetRelease.validation_passed.is_(True),
        )
        .scalar_subquery()
    )
    return stmt.where(Game.release_id == active_release)
