"""Add expand-only generated player fact catalog.

Revision ID: 0003_generated_stat_facts
Revises: 0002_release_game_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_generated_stat_facts"
down_revision = "0002_release_game_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "generated_stat_facts" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "generated_stat_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("dataset_releases.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fact_type", sa.String(64), nullable=False),
        sa.Column("player_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("stat_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("timeframe_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_game_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("score_components_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("detector_version", sa.String(64), nullable=False),
        sa.Column("data_through", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("release_id", "fingerprint"),
    )
    op.create_index("ix_generated_stat_facts_release_id", "generated_stat_facts", ["release_id"])
    op.create_index("ix_generated_stat_facts_fact_type", "generated_stat_facts", ["fact_type"])
    op.create_index(
        "ix_generated_facts_release_type_score",
        "generated_stat_facts",
        ["release_id", "fact_type", "total_score"],
    )


def downgrade() -> None:
    # Expand-only: older images safely ignore this table.
    pass
