"""Ordinary production-router reasoning contract through HTTP, SQL and Redis.

Specified before the payload cutover: optional reasoning models can reject
``effort:none`` even though the gateway exposes that effort globally; emitting
it must not silently turn an answer into factual fallback. Unspecified reasoning
must retain provider defaults, explicit efforts must survive unchanged, and
non-OpenRouter transports must receive no OpenRouter extensions. Provider errors
and disabled providers still deliver cited, committed fallback without retries.
These isolated transport responses are protocol evidence, not live certification.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app import main
from app.api.router import build_api_router
from app.core.config import get_settings
from app.evaluation.trace_capture import capture_turn
from app.tests.test_analyst_contracts import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def ordinary_router(db_session, local_redis, monkeypatch, request):  # noqa: F811
    settings = get_settings()
    # The engine was created in TEST_MODE before changing the runtime adapter.
    # Never reconnect to the configured production database or Redis.
    assert db_session.bind.dialect.name == "sqlite"
    await _seed_release_stats(db_session)
    for key, value in {
        "environment": "production",
        "test_mode": False,
        "sentry_dsn": None,
        "ai_provider": "openrouter",
        "redis_url": f"redis://127.0.0.1:{local_redis.connection_pool.connection_kwargs['port']}/0",
        "ai_api_key": "synthetic-no-paid-calls",
        "ai_base_url": "https://openrouter.ai/api/v1",
        "ai_chat_model": "synthetic/optional-reasoning",
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary",
        "analyst_provider_format": "json_object",
        "rag_qdrant_enabled": False,
        "rag_hybrid_enabled": False,
    }.items():
        monkeypatch.setattr(settings, key, value)
    ledger = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(ledger, "0.125")
    # main.api_router was constructed when the shared fixtures imported the
    # app; select the real production route builder, not a private guard.
    monkeypatch.setattr(main, "api_router", build_api_router(production=True))
    address = hashlib.sha256(request.node.nodeid.encode()).digest()[:3]
    client_ip = "127." + ".".join(str(byte) for byte in address)
    async with AsyncClient(
        transport=ASGITransport(app=main.create_app(), client=(client_ip, 12345)),
        base_url="https://test",
    ) as client:
        yield client, local_redis, ledger, settings


@pytest.mark.parametrize(
    ("backend", "effort", "outcome"),
    [
        ("openrouter", "none", "supported"),
        ("openrouter", None, "supported"),
        ("openrouter", "low", "supported"),
        ("openrouter", "high", "supported"),
        ("openrouter", "medium", "supported"),
        ("openrouter", "minimal", "supported"),
        ("compatible", "none", "supported"),
        ("compatible", "medium", "supported"),
        ("compatible", None, "supported"),
        ("openrouter", "none", "http_error"),
        ("openrouter", "none", "disabled"),
        ("openrouter", "none", "missing_key"),
    ],
)
async def test_ordinary_router_reasoning_http(
    ordinary_router, monkeypatch, tmp_path, record_property, backend, effort, outcome
):
    client, redis, ledger, settings = ordinary_router
    monkeypatch.setattr(settings, "ai_reasoning_effort", effort)
    if backend == "compatible":
        monkeypatch.setattr(settings, "ai_base_url", "https://compatible.invalid/v1")
    if outcome == "disabled":
        monkeypatch.setattr(settings, "ai_provider", "disabled")
    elif outcome == "missing_key":
        monkeypatch.setattr(settings, "ai_api_key", None)

    # Reflect optional model metadata: globally accepted efforts are not all
    # supported by every model. Explicit-effort cases use compatible fixtures.
    supported_efforts = ["max", "high", "low"]
    if effort in {"minimal", "medium"}:
        supported_efforts.append(effort)
    metadata = {
        "mandatory": False,
        "default_enabled": True,
        "default_effort": "high",
        "supported_efforts": supported_efforts,
    }
    protocol = ScriptedAdapter()
    event_loop = asyncio.get_running_loop()
    exchanges = []

    def isolated_urlopen(request, *, timeout, context):
        assert request.full_url == f"{settings.ai_base_url}/chat/completions"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer synthetic-no-paid-calls"
        assert timeout > 0 and context.check_hostname
        body = json.loads(request.data)
        exchange = {"url": request.full_url, "request": body}
        exchanges.append(exchange)
        # Every outbound attempt is retained before validation, including the
        # pre-cutover effort:none rejection; no real urlopen is ever delegated.
        if backend == "openrouter":
            reasoning = body.get("reasoning")
            if reasoning and "effort" in reasoning:
                if reasoning["effort"] not in metadata["supported_efforts"]:
                    error = {"error": {"message": "Unsupported reasoning effort for model"}}
                    exchange.update(status=400, response=error)
                    raise urllib.error.HTTPError(
                        request.full_url,
                        400,
                        "Unsupported effort",
                        {},
                        io.BytesIO(json.dumps(error).encode()),
                    )
            expected = (
                {"enabled": False}
                if effort == "none"
                else {"effort": effort}
                if effort is not None
                else None
            )
            assert reasoning == expected
        else:
            assert "reasoning" not in body and "reasoning_effort" not in body
            assert "provider" not in body
        if outcome == "http_error":
            error = {"error": {"message": "Synthetic provider unavailable"}}
            exchange.update(status=400, response=error)
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Synthetic provider error",
                {},
                io.BytesIO(json.dumps(error).encode()),
            )
        messages = body["messages"]
        future = asyncio.run_coroutine_threadsafe(
            protocol.generate(system=messages[0]["content"], user=messages[1]["content"]),
            event_loop,
        )
        raw = future.result(timeout=5)
        provider_response = {
            "id": f"synthetic-generation-{len(exchanges)}",
            "model": settings.ai_chat_model,
            "provider": "synthetic-ordinary-router",
            "usage": {"cost": 0, "completion_tokens_details": {"reasoning_tokens": 0}},
            "choices": [{"finish_reason": "stop", "message": {"content": raw}}],
        }
        exchange.update(status=200, response=provider_response)
        return io.BytesIO(json.dumps(provider_response).encode())

    monkeypatch.setattr("urllib.request.urlopen", isolated_urlopen)
    name = f"{backend}-{effort or 'unspecified'}-{outcome}"
    payload = {
        "question": "Tell me an interesting Jalen Brunson stat.",
        "season": "2025-26",
        "turn_id": f"ordinary-reasoning-{name}",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    calls_before_replay = len(exchanges)
    with capture_turn() as replay_capture:
        replay = await client.post("/analysis/query", json=payload)
    receipt = {
        "artifact_version": "ordinary-router-reasoning-http-v1",
        "failure_mode": name,
        "transport": "isolated urllib boundary; synthetic provider responses",
        "model_reasoning_metadata": metadata,
        "consumer_request": payload,
        "status": response.status_code,
        "response": response.json(),
        "capture": capture,
        "provider_exchanges": exchanges,
        "calls_before_replay": calls_before_replay,
        "calls_after_replay": len(exchanges),
        "replay_status": replay.status_code,
        "replay": replay.json(),
        "replay_capture": replay_capture,
        "monthly_before": "0.125",
        "monthly_after": (await redis.get(ledger)).decode(),
        "paid_provider_requests": 0,
        "live_provider_certification": False,
    }
    directory = Path(os.environ.get("KNICKSIQ_ROUTER_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / f"{name}.json"
    with artifact.open("x") as retained:
        json.dump(receipt, retained, indent=2)
    record_property("ordinary_router_reasoning_artifact", str(artifact))

    assert response.status_code == replay.status_code == 200, receipt
    result = response.json()
    assert result["answer"] and result["citations"] and result["state_committed"]
    assert result["revision"] == 1
    assert result == replay.json()
    assert len(exchanges) == calls_before_replay
    assert replay_capture["turn"]["model_calls"] == 0
    assert response.headers["Strict-Transport-Security"]
    assert "capture" not in result and "provider_exchanges" not in result
    if outcome == "supported":
        assert exchanges and result["llm_validated"] and not result["degraded"], receipt
        assert any(
            json.loads(e["request"]["messages"][1]["content"])["schema"]["title"] == "AnswerReview"
            for e in exchanges
        )
        assert all(
            e["response"]["model"] == settings.ai_chat_model
            and e["response"]["provider"] == "synthetic-ordinary-router"
            and e["response"]["id"]
            for e in exchanges
        )
        assert receipt["monthly_after"] == receipt["monthly_before"]
    else:
        assert result["degraded"] and not result["llm_validated"]
        assert len(exchanges) == (1 if outcome == "http_error" else 0), receipt
