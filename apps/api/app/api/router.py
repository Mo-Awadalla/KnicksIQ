"""Aggregate router for the API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import analysis, archive, games, health, jobs, players, reports, teams
from app.core.config import get_settings

PUBLIC_GET_PATHS = {
    "/",
    "/health/live",
    "/health/ready",
    "/archive/status",
    "/games",
    "/games/{game_id}",
    "/games/{game_id}/box-score",
    "/games/{game_id}/play-by-play",
    "/games/{game_id}/runs",
    "/players",
    "/players/{player_id}",
    "/teams",
    "/teams/{team_id}",
    "/reports",
    "/reports/{report_id}",
}


def build_api_router(*, production: bool) -> APIRouter:
    router = APIRouter()
    if production:
        for source in (
            health.router,
            archive.router,
            games.router,
            players.router,
            teams.router,
            reports.router,
        ):
            router.routes.extend(
                route
                for route in source.routes
                if "GET" in getattr(route, "methods", set())
                and getattr(route, "path", "") in PUBLIC_GET_PATHS
            )
        router.routes.extend(
            route
            for route in analysis.router.routes
            if getattr(route, "path", "") == "/analysis/query"
            and "POST" in getattr(route, "methods", set())
        )
        return router

    router.include_router(health.router)
    router.include_router(archive.router)
    router.include_router(games.router)
    router.include_router(players.router)
    router.include_router(teams.router)
    router.include_router(reports.router)
    router.include_router(analysis.router)
    router.include_router(jobs.router)
    return router


api_router = build_api_router(production=get_settings().is_production)
