"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    When `test_mode` is True, the DB URL is forced to an in-memory
    SQLite database so unit/integration tests can run without a
    Postgres instance.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "knicksiq-api"
    environment: str = Field(default="development")
    debug: bool = False
    test_mode: bool = False

    db_url: str = "postgresql+asyncpg://knicksiq:knicksiq@localhost:5432/knicksiq"
    db_echo: bool = False
    db_pool_size: int = 5
    seed_on_startup: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    admin_api_key: str | None = None

    ai_provider: str = "mock"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_chat_model: str = "gpt-4o-mini"
    ai_embedding_model: str = "text-embedding-3-small"
    ai_request_timeout_seconds: float = 20.0

    openrouter_api_key: str | None = None
    openrouter_summary_model: str = "poolside/laguna-xs-2.1:free"
    qdrant_url: str | None = None
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_timeout_seconds: float = 5.0
    qdrant_collection: str = "knicksiq_possessions"
    rag_qdrant_enabled: bool = False
    rag_hybrid_enabled: bool = False
    rag_reranker_enabled: bool = False
    rag_llm_planner_enabled: bool = False
    rag_qdrant_vector_size: int = 1024
    rag_qdrant_games_collection: str = "knicks_games"
    rag_qdrant_possessions_collection: str = "knicks_possessions"
    rag_qdrant_roster_collection: str = "knicks_roster"
    rag_embedding_model: str = "BAAI/bge-large-en-v1.5"
    rag_embedding_batch_size: int = 64
    rag_embedding_max_seq_length: int = 128
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_retrieval_limit: int = 5
    rag_rerank_limit: int = 20
    rag_planner_confidence_threshold: float = 0.7

    public_chat_rate_limit_per_minute: int = 20
    public_chat_max_prompt_chars: int = 1200

    @property
    def effective_db_url(self) -> str:
        if self.test_mode:
            return "sqlite+aiosqlite:///:memory:"
        if self.db_url.startswith("postgresql://"):
            return self.db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.db_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
