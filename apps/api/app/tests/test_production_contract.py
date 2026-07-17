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


def test_render_blueprint_enables_the_grounded_ai_configuration():
    blueprint_path = Path(__file__).parents[4] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())
    api = next(service for service in blueprint["services"] if service["name"] == "knicksiq-api")
    env = {item["key"]: item.get("value") for item in api["envVars"]}

    model = "google/gemini-3.1-flash-lite"
    assert env["AI_PROVIDER"] == "openrouter"
    assert env["AI_CHAT_MODEL"] == model
    assert env["OPENROUTER_ALLOWED_MODELS"] == f'["{model}"]'
    assert env["OPENROUTER_SUMMARY_MODEL"] == model
    assert env["RAG_LLM_PLANNER_ENABLED"] == "true"


def test_render_blueprint_provisions_the_optional_runtime_store():
    blueprint_path = Path(__file__).parents[4] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())
    runtime_store = next(
        service for service in blueprint["services"] if service["name"] == "knicksiq-redis"
    )
    api = next(service for service in blueprint["services"] if service["name"] == "knicksiq-api")
    redis_url = next(item for item in api["envVars"] if item["key"] == "REDIS_URL")

    assert runtime_store == {
        "type": "keyvalue",
        "name": "knicksiq-redis",
        "plan": "free",
        "region": "oregon",
        "ipAllowList": [],
        "maxmemoryPolicy": "allkeys-lru",
        "persistenceMode": "off",
    }
    assert redis_url["fromService"] == {
        "type": "keyvalue",
        "name": "knicksiq-redis",
        "property": "connectionString",
    }
