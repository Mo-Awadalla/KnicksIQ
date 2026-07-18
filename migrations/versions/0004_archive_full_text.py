"""Add PostgreSQL archive full-text and player-name trigram indexes.

Revision ID: 0004_archive_full_text
Revises: 0003_generated_stat_facts
"""

from __future__ import annotations

from alembic import op

revision = "0004_archive_full_text"
down_revision = "0003_generated_stat_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_players_full_name_trgm "
        "ON players USING gin (lower(full_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_text_fts "
        "ON chunks USING gin (to_tsvector('simple', coalesce(text, '')))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_game_events_description_fts "
        "ON game_events USING gin (to_tsvector('simple', coalesce(description, '')))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reports_text_fts ON reports USING gin "
        "(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '') || "
        "' ' || coalesce(turning_point, '')))"
    )


def downgrade() -> None:
    # Expand-only indexes are safe for older application versions to ignore.
    pass
