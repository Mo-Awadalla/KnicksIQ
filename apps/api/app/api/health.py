"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.services.qdrant_client import is_qdrant_healthy

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/rag")
async def rag_health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "qdrant_enabled": settings.rag_qdrant_enabled,
        "qdrant_healthy": is_qdrant_healthy(),
        "embedding_model": settings.rag_embedding_model,
        "reranker_enabled": settings.rag_reranker_enabled,
    }


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "knicksiq-api",
        "description": "KnicksIQ FastAPI backend",
        "docs": "/docs",
    }
