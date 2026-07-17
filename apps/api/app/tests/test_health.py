"""Operational health response tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.api import health


async def test_ready_distinguishes_disabled_optional_services(client, monkeypatch):
    settings = SimpleNamespace(
        require_active_release=False,
        test_mode=True,
        is_production=False,
        rag_qdrant_enabled=False,
        redis_url=None,
        ai_provider="mock",
        openrouter_api_key=None,
        ai_api_key=None,
    )
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    monkeypatch.setattr(health, "is_qdrant_healthy", lambda: False)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["optional_dependencies"] == {
        "qdrant": "disabled",
        "redis": "disabled",
        "openrouter": "disabled",
    }
