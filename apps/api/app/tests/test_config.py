"""Configuration normalization tests."""

import pytest
from app.core.config import Settings
from pydantic import ValidationError


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


def test_qdrant_timeout_requires_at_least_one_whole_second():
    with pytest.raises(ValidationError):
        Settings.model_validate({"qdrant_timeout_seconds": 0.5})

    assert Settings(qdrant_timeout_seconds=1).qdrant_timeout_seconds == 1
