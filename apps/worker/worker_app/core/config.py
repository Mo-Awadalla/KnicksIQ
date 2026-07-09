"""Worker configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NbaApiSettings(BaseSettings):
    """Settings for the live nba_api-backed data source.

    Reads env vars prefixed `NBA_API_` (e.g. `NBA_API_SEASONS`).
    """

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, env_prefix="NBA_API_"
    )

    seasons: str = "2021-22,2022-23,2023-24,2024-25,2025-26"
    timeout_seconds: int = 30
    proxy_url: str | None = None
    rate_remaining_per_minutes: int = 10
    user_agent: str = "KnicksIQ/0.1 (sports analytics)"
    retry_attempts: int = 3
    retry_backoff_seconds: float = 2.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    worker_name: str = "knicksiq-worker"
    environment: str = "development"
    test_mode: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    db_url: str = "postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq"

    redis_url: str = "redis://localhost:6379/0"
    redis_db: int = 0

    default_queue: str = "default"
    job_timeout: int = 300  # seconds

    data_source: Literal["static", "nba_api"] = Field(
        default="static", validation_alias=AliasChoices("NBA_DATA_SOURCE", "data_source")
    )
    nba_api: NbaApiSettings = Field(default_factory=NbaApiSettings)

    @property
    def effective_db_url(self) -> str:
        if self.test_mode:
            return "sqlite+aiosqlite:///:memory:"
        return self.db_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
