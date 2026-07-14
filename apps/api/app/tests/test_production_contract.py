"""The production API exposes only the documented immutable public surface."""

from __future__ import annotations

from pathlib import Path

import yaml
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


def test_render_blueprint_uses_only_free_tier_supported_fields():
    blueprint_path = Path(__file__).parents[4] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())
    free_services = [service for service in blueprint["services"] if service.get("plan") == "free"]

    assert free_services
    assert all("preDeployCommand" not in service for service in free_services)
    assert "databases" not in blueprint
