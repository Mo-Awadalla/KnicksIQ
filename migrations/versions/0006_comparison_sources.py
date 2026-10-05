"""Store independently verified comparison proof separately from canonical rows.

Revision ID: 0006_comparison_sources
Revises: 0005_player_analytics_views
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_comparison_sources"
down_revision = "0005_player_analytics_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial migration builds current metadata; upgrades of older stores do not.
    if "comparison_sources" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "comparison_sources",
        sa.Column(
            "release_id",
            sa.Integer(),
            sa.ForeignKey("dataset_releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_review_sha256", sa.String(64), nullable=False),
        sa.Column("trajectories_sha256", sa.String(64), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("comparison_json", sa.Text(), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=False),
        sa.Column("facts_sha256", sa.String(64), nullable=False),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("bindings_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    # Expand-only rollback retains the independently verified release proof.
    pass
