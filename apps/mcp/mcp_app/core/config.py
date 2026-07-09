"""MCP server configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    server_name: str = "knicksiq-mcp"
    environment: str = "development"
    test_mode: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    db_url: str = "postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq"

    sse_host: str = "0.0.0.0"
    sse_port: int = 8001

    @property
    def effective_db_url(self) -> str:
        if self.test_mode:
            return "sqlite+aiosqlite:///:memory:"
        return self.db_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
