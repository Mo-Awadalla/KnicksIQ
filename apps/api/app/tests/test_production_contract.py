"""The production API exposes only the documented immutable public surface."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_render_blueprint_uses_only_free_tier_supported_fields():
    blueprint_path = Path(__file__).parents[4] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())
    free_services = [service for service in blueprint["services"] if service.get("plan") == "free"]

    assert free_services
    assert all("preDeployCommand" not in service for service in free_services)
    assert "databases" not in blueprint


def test_render_blueprint_provisions_the_optional_runtime_store():
    blueprint_path = Path(__file__).parents[4] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())
    runtime_store = next(
        service for service in blueprint["services"] if service["name"] == "knicksiq-redis"
    )
    api = next(service for service in blueprint["services"] if service["name"] == "knicksiq-api")
    redis_url = next(item for item in api["envVars"] if item["key"] == "REDIS_URL")

    assert runtime_store["type"] == "keyvalue"
    assert runtime_store["maxmemoryPolicy"] == "allkeys-lru"
    assert runtime_store["persistenceMode"] == "off"
    assert redis_url["fromService"] == {
        "type": "keyvalue",
        "name": "knicksiq-redis",
        "property": "connectionString",
    }
