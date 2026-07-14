"""The production API exposes only the documented immutable public surface."""

from __future__ import annotations

from app.api.router import PUBLIC_GET_PATHS, build_api_router


def test_production_route_allowlist_is_exact():
    routes = build_api_router(production=True).routes
    get_paths = {
        getattr(route, "path", "") for route in routes if "GET" in getattr(route, "methods", set())
    }
    post_paths = {
        getattr(route, "path", "") for route in routes if "POST" in getattr(route, "methods", set())
    }
    assert get_paths == PUBLIC_GET_PATHS
    assert post_paths == {"/analysis/query"}
    assert not any(
        blocked in getattr(route, "path", "")
        for route in routes
        for blocked in ("jobs", "ingest", "bad-stretches", "generate", "admin")
    )
