"""Alembic environment for the asynchronous application database."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.config import get_settings
from app.models import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().effective_db_url)
target_metadata = Base.metadata

_MIGRATION_MANAGED_INDEXES = {
    "ix_chunks_text_fts",
    "ix_game_events_description_fts",
    "ix_players_full_name_trgm",
    "ix_reports_text_fts",
}


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Keep expression indexes managed by their explicit expand-only migration."""
    if type_ == "index" and reflected and name in _MIGRATION_MANAGED_INDEXES:
        return False
    return True


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async_migrations())
