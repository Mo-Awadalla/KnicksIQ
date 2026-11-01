"""Facts reach a real socket client while the provider request is still open."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import shutil
import time

import httpx
import pytest
from app.tests.support.live_shadow import SHADOW_SECRET, LiveShadowRuntime
from redis.asyncio import Redis

QUESTION = "What did Jalen Brunson average in his last 2 appearances?"
TURN = "live-shadow-turn"
PAYLOAD = {
    "question": QUESTION,
    "season": "2025-26",
    "turn_id": TURN,
    "expected_revision": 0,
}


@pytest.fixture(scope="function")
async def live_shadow(tmp_path):
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server is required for the live shadow delivery check")
    runtime = LiveShadowRuntime(tmp_path)
    try:
        yield await runtime.start()
    finally:
        runtime.stop()


async def _settled(provider, *, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if provider.in_flight == 0:
            before = provider.requests
            await asyncio.sleep(0.25)
            if provider.in_flight == 0 and provider.requests == before:
                return before
        await asyncio.sleep(0.05)
    raise TimeoutError("the shadow trial never settled")


async def test_facts_arrive_while_the_provider_is_blocked(live_shadow):
    async with httpx.AsyncClient(base_url=live_shadow.base_url, timeout=60) as client:
        started = time.monotonic()
        response = await client.post(
            "/analysis/query", json=PAYLOAD, headers={"x-request-id": "live-blocked-provider"}
        )
        elapsed = time.monotonic() - started
        assert response.status_code == 200, response.text
        body = response.json()
        # The trial is still open at this instant: the client's facts never waited for it.
        assert live_shadow.provider.entered.wait(timeout=15)
        assert live_shadow.provider.in_flight == 1
        assert not live_shadow.provider.release.is_set()
        assert elapsed < 15, f"facts waited {elapsed:.1f}s on a provider that never answered"
        assert body["citations"] and "25" in body["answer"], body
        assert body["route"] == "factual_fallback" and body["llm_validated"] is False
        assert body["degraded"] is False and body["warnings"] == []
        assert body["state_committed"] is True and body["revision"] == 1

        redis = Redis.from_url(f"redis://127.0.0.1:{live_shadow.redis_port}/0", socket_timeout=2)
        try:
            token = hmac.new(
                SHADOW_SECRET.encode(), ("analyst-session:" + TURN).encode(), hashlib.sha256
            ).hexdigest()
            key = f"analyst:{{{token}}}"
            assert await redis.hget(key, "revision") == b"1"
            committed = await redis.hget(key, f"turn:{TURN}")
        finally:
            await redis.aclose()
        assert committed is not None
        stored = json.loads(json.loads(committed)["response"])
        assert stored["answer"] == body["answer"] and stored["revision"] == body["revision"]

        live_shadow.provider.release.set()
        trial_requests = await _settled(live_shadow.provider)
        assert trial_requests >= 1

        replay = await client.post(
            "/analysis/query", json=PAYLOAD, headers={"x-request-id": "live-blocked-replay"}
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == body
        await asyncio.sleep(0.5)
        assert live_shadow.provider.requests == trial_requests


async def test_shutdown_stays_bounded_while_the_provider_is_blocked(tmp_path):
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server is required for the live shadow delivery check")
    runtime = LiveShadowRuntime(
        tmp_path,
        overrides={"ANALYST_DEADLINE_SECONDS": "3", "AI_REQUEST_TIMEOUT_SECONDS": "2"},
    )
    try:
        await runtime.start()
        async with httpx.AsyncClient(base_url=runtime.base_url, timeout=60) as client:
            response = await client.post(
                "/analysis/query", json=PAYLOAD, headers={"x-request-id": "live-shutdown"}
            )
            assert response.status_code == 200, response.text
            assert "25" in response.json()["answer"]
            assert runtime.provider.entered.wait(timeout=10)
            assert runtime.provider.in_flight == 1
            started = time.monotonic()
            runtime.stop()
            elapsed = time.monotonic() - started
        assert elapsed < 10, f"shutdown waited {elapsed:.1f}s on a blocked provider"
    finally:
        runtime.stop()
