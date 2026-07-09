"""Aggregate router for the API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import analysis, games, health, jobs, players, reports, teams

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(games.router)
api_router.include_router(players.router)
api_router.include_router(teams.router)
api_router.include_router(jobs.router)
api_router.include_router(reports.router)
api_router.include_router(analysis.router)
