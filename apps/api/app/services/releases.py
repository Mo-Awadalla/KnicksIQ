"""Reusable active-release filtering for public reads."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from sqlalchemy import exists, or_, select


def enforces_active_release() -> bool:
    """Whether a reader must be limited to the validated active release.

    Production always enforces the boundary. Development enforces it whenever a
    developer has not explicitly opted out, so a development server cannot serve
    historical or staged rows that production would hide.
    """
    settings = get_settings()
    return settings.is_production or (not settings.test_mode and settings.require_active_release)


def _active_release_id() -> Any:
    """The validated active release id.

    The system invariant is exactly one active validated release. A scalar subquery
    keeps that invariant loud: two active rows raise instead of silently unioning two
    releases into one public read.
    """
    return (
        select(DatasetRelease.id)
        .where(
            DatasetRelease.status == "active",
            DatasetRelease.validation_passed.is_(True),
        )
        .scalar_subquery()
    )


def restrict_to_active_release(stmt: Any) -> Any:
    if not enforces_active_release():
        return stmt
    return stmt.where(Game.release_id == _active_release_id())


def restrict_players_to_active_release(stmt: Any) -> Any:
    """Keep only players who appear in the active release's box-score facts."""
    if not enforces_active_release():
        return stmt
    member = exists(
        select(PlayerGameStat.id).where(
            PlayerGameStat.player_id == Player.id,
            PlayerGameStat.release_id == _active_release_id(),
        )
    )
    return stmt.where(member)


def restrict_teams_to_active_release(stmt: Any) -> Any:
    """Keep only teams that appear in an active-release game.

    Games are the authoritative membership source: a summary-only game still names
    both teams, while box-score facts may be absent for it.
    """
    if not enforces_active_release():
        return stmt
    active = _active_release_id()
    home = select(Game.home_team_id).where(Game.release_id == active)
    away = select(Game.away_team_id).where(Game.release_id == active)
    return stmt.where(or_(Team.id.in_(home), Team.id.in_(away)))
