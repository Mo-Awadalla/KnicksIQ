"""Liveness and readiness probes with optional-dependency degradation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.dataset_release import DatasetRelease
from app.services.qdrant_client import is_qdrant_healthy

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health() -> dict[str, str]:
    return await live()


@router.get("/health/ready")
async def ready(db: Annotated[AsyncSession, Depends(get_db)]):
    settings = get_settings()
    failures: list[str] = []
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        failures.append("postgres")

    release = None
    if not failures:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active",
                    DatasetRelease.validation_passed.is_(True),
                )
            )
        ).scalar_one_or_none()
    if settings.require_active_release and not settings.test_mode and release is None:
        failures.append("active_release")
    if settings.is_production:
        if settings.ip_hash_secret == "development-only-change-me":
            failures.append("ip_hash_secret")
        if settings.public_web_origin not in settings.cors_origins:
            failures.append("cors_origin")
        if settings.ai_provider == "openrouter" and not settings.openrouter_allowed_models:
            failures.append("openrouter_model_allowlist")

    optional = {
        "qdrant": (
            "disabled"
            if not settings.rag_qdrant_enabled
            else "ok"
            if is_qdrant_healthy()
            else "degraded"
        ),
        "redis": "configured" if settings.redis_url else "disabled",
        "openrouter": (
            "disabled"
            if settings.ai_provider.lower() != "openrouter"
            else "configured"
            if settings.openrouter_api_key or settings.ai_api_key
            else "degraded"
        ),
    }
    body = {
        "status": "ready" if not failures else "not_ready",
        "data_version": release.version if release else None,
        "required_failures": failures,
        "optional_dependencies": optional,
    }
    return JSONResponse(status_code=200 if not failures else 503, content=body)


@router.get("/health/rag")
async def rag_health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok" if is_qdrant_healthy() else "degraded",
        "qdrant_enabled": settings.rag_qdrant_enabled,
        "qdrant_healthy": is_qdrant_healthy(),
    }


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "knicksiq-api",
        "description": "Unofficial Knicks 2025-26 archive",
    }
