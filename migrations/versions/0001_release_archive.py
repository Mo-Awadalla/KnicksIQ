"""Create the release-scoped public archive schema.

Revision ID: 0001_release_archive
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.models import Base
from sqlalchemy import inspect

revision = "0001_release_archive"
down_revision = None
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _keys(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {
        str(item["name"])
        for item in [
            *inspector.get_indexes(table),
            *inspector.get_unique_constraints(table),
        ]
        if item.get("name")
    }


def upgrade() -> None:
    # Creates a complete empty database. For an existing pre-Alembic database,
    # checkfirst preserves current tables and the batch operations add release linkage.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    if "release_id" not in _columns("games"):
        with op.batch_alter_table("games") as batch:
            batch.add_column(
                sa.Column(
                    "release_id",
                    sa.Integer(),
                    sa.ForeignKey("dataset_releases.id"),
                    nullable=True,
                )
            )
    report_columns = _columns("reports")
    if "release_id" not in report_columns:
        with op.batch_alter_table("reports") as batch:
            batch.add_column(
                sa.Column(
                    "release_id",
                    sa.Integer(),
                    sa.ForeignKey("dataset_releases.id"),
                    nullable=True,
                )
            )
            batch.add_column(
                sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false())
            )
            batch.add_column(sa.Column("content_sha256", sa.String(length=64), nullable=True))
    if "release_id" not in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.add_column(
                sa.Column(
                    "release_id",
                    sa.Integer(),
                    sa.ForeignKey("dataset_releases.id"),
                    nullable=True,
                )
            )
    desired_indexes = {
        "games": [
            ("ix_games_release_id", ["release_id"], False),
            ("uq_games_release_nba_game", ["release_id", "nba_game_id"], True),
            ("ix_games_release_season_date", ["release_id", "season", "game_date"], False),
        ],
        "game_events": [
            ("ix_game_events_game_team_type", ["game_id", "team_id", "event_type"], False),
        ],
        "reports": [
            ("ix_reports_release_id", ["release_id"], False),
            ("ix_reports_reviewed", ["reviewed"], False),
            ("uq_reports_release_game_type_idx", ["release_id", "game_id", "report_type"], True),
            ("ix_reports_release_game", ["release_id", "game_id"], False),
        ],
        "documents": [
            ("ix_documents_release_id", ["release_id"], False),
            (
                "uq_documents_release_source_game_title_idx",
                ["release_id", "source_type", "game_id", "title"],
                True,
            ),
            (
                "ix_documents_release_source_game",
                ["release_id", "source_type", "game_id"],
                False,
            ),
        ],
    }
    for table, indexes in desired_indexes.items():
        existing_keys = _keys(table)
        for name, columns, unique in indexes:
            if name not in existing_keys:
                op.create_index(name, table, columns, unique=unique)


def downgrade() -> None:
    # Expand-only migrations let the previous application revision run safely:
    # new linkage is nullable and new tables are ignored by old code. A downgrade
    # therefore only moves Alembic's revision marker and never destroys archive data.
    pass
