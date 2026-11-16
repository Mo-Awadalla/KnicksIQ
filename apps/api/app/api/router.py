from __future__ import annotations

from fastapi import APIRouter

from app.api import chat, health, jobs
from app.core.config import get_settings

PUBLIC_HEALTH_PATHS = {"/health/live", "/health/ready"}


def build_api_router(*, production: bool) -> APIRouter:
    router = APIRouter()
    if production:
        router.routes.extend(
            route
            for route in health.router.routes
            if getattr(route, "path", "") in PUBLIC_HEALTH_PATHS
        )
        router.include_router(chat.router)
        return router

    router.include_router(health.router)
    router.include_router(chat.router)
    router.include_router(jobs.router)
    return router


api_router = build_api_router(production=get_settings().is_production)
