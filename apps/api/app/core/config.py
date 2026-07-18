"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    db_max_overflow: int = 5
    db_pool_timeout_seconds: float = 5.0
    db_statement_timeout_ms: int = 3000
    seed_on_startup: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    redis_url: str | None = None

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "test"]
    )
    public_web_origin: str = "http://localhost:5173"
    ip_hash_secret: str = "development-only-change-me"

    admin_api_key: str | None = None

    ai_provider: str = "mock"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_chat_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    ai_embedding_model: str = "text-embedding-3-small"
    ai_request_timeout_seconds: float = 2.5

    openrouter_api_key: str | None = None
    openrouter_summary_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_timeout_seconds: int = Field(default=5, ge=1)
    qdrant_collection: str = "knicksiq_possessions"
    rag_qdrant_enabled: bool = False
    rag_qdrant_cloud_inference: bool = False
    rag_hybrid_enabled: bool = False
    rag_reranker_enabled: bool = False
    rag_llm_planner_enabled: bool = True
    rag_qdrant_vector_size: int = 384
    rag_qdrant_games_collection: str = "knicks_games"
    rag_qdrant_possessions_collection: str = "knicks_possessions"
    rag_qdrant_roster_collection: str = "knicks_roster"
    rag_qdrant_box_scores_collection: str = "knicks_box_scores"
    rag_qdrant_reports_collection: str = "knicks_reports"
    rag_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rag_embedding_device: str | None = None
    rag_embedding_batch_size: int = 64
    rag_embedding_max_seq_length: int = 128
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_retrieval_limit: int = 5
    rag_rerank_limit: int = 20
    rag_planner_confidence_threshold: float = 0.7
    analysis_answer_mode: Literal["deterministic", "shadow", "llm_primary"] = "deterministic"
    analysis_shadow_sample_rate: float = Field(default=0.1, ge=0, le=1)
    analysis_prompt_version: str = "v1"

    public_chat_rate_limit_per_minute: int = 10
    public_chat_rate_limit_per_day: int = 100
    public_chat_max_prompt_chars: int = 1200
    public_chat_max_context_messages: int = 4
    dataset_season: str = "2025-26"
    require_active_release: bool = True
    sentry_dsn: str | None = None
    openrouter_monthly_cutoff_usd: float = 8.0
    openrouter_allowed_models: list[str] = Field(default_factory=list)

    @property
    def effective_db_url(self) -> str:
        if self.test_mode:
            return "sqlite+aiosqlite:///:memory:"
        url = self.db_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql+asyncpg://"):
            parts = urlsplit(url)
            query = [
                ("ssl" if key == "sslmode" else key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key != "channel_binding"
            ]
            url = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
            )
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
