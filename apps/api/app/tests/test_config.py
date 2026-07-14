"""Configuration normalization tests."""

from app.core.config import Settings


def test_neon_connection_string_is_normalized_for_asyncpg():
    settings = Settings(
        test_mode=False,
        db_url=(
            "postgresql://user:password@ep-example.neon.tech/neondb"
            "?sslmode=require&channel_binding=require"
        ),
    )

    assert settings.effective_db_url == (
        "postgresql+asyncpg://user:password@ep-example.neon.tech/neondb?ssl=require"
    )
