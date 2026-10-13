"""Retain source scoreboard presence without rewriting historical score rows.

Revision ID: 0007_event_score_presence
Revises: 0006_comparison_sources
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_event_score_presence"
down_revision = "0006_comparison_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial migration creates current metadata; existing rows remain unknown.
    columns = sa.inspect(op.get_bind()).get_columns("game_events")
    if "score_observed" not in {column["name"] for column in columns}:
        op.add_column("game_events", sa.Column("score_observed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Expand-only rollback retains source presence for a later forward recovery.
    pass
