"""Make game identity release-scoped on upgraded legacy databases.

Revision ID: 0002_release_game_identity
Revises: 0001_release_archive
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0002_release_game_identity"
down_revision = "0001_release_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {item["name"]: item for item in inspect(op.get_bind()).get_indexes("games")}
    legacy = indexes.get("ix_games_nba_game_id")
    if legacy and legacy.get("unique"):
        op.drop_index("ix_games_nba_game_id", table_name="games")
        op.create_index("ix_games_nba_game_id", "games", ["nba_game_id"], unique=False)


def downgrade() -> None:
    # Multiple release rows can share an NBA game id. Reinstating the global
    # unique index would make rollback destructive or impossible.
    pass
