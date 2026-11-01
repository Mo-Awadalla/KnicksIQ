"""Prove the client's facts arrive while the provider request is still open.

Boots the real API (uvicorn, real socket), a real Redis, a sqlite database with a seeded
release, and an OpenAI-compatible provider endpoint that holds every completion until this
script releases it. No paid provider is contacted.

    uv run --package knicksiq-api python tools/release/shadow_isolation_probe.py \
        --out release-artifacts/production-readiness-20261030/shadow-isolation.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import shutil
import tempfile
import time
from pathlib import Path

import httpx
from app.api.analysis_retrieval import _sample_shadow
from app.core.config import get_settings
from app.tests.support.live_shadow import SHADOW_SECRET, LiveShadowRuntime
from redis.asyncio import Redis

QUESTION = "What did Jalen Brunson average in his last 2 appearances?"
TURN = "shadow-isolation-probe"
PAYLOAD = {"question": QUESTION, "season": "2025-26", "turn_id": TURN, "expected_revision": 0}


def _steering_measurement() -> dict[str, object]:
    """How much of a caller-enumerated request-id bucket the policy actually samples."""
    settings = get_settings()
    original = settings.ip_hash_secret
    settings.ip_hash_secret = "probe-server-secret"
    try:
        rate = 0.1
        forced = [
            f"steer-{index}"
            for index in range(4000)
            if int.from_bytes(hashlib.sha256(f"steer-{index}".encode()).digest()[:4], "big")
            / (2**32 - 1)
            < rate
        ]
        sampled = [request_id for request_id in forced if _sample_shadow(request_id, rate)]
        population = [f"population-{index}" for index in range(2000)]
        share = sum(_sample_shadow(request_id, rate) for request_id in population) / len(population)
        rotated_settings = settings.ip_hash_secret
        settings.ip_hash_secret = "probe-rotated-secret"
        rotated = [request_id for request_id in forced if _sample_shadow(request_id, rate)]
        settings.ip_hash_secret = rotated_settings
        return {
            "caller_enumerated_ids": len(forced),
            "sampled_from_caller_bucket": len(sampled),
            "caller_bucket_hit_rate": round(len(sampled) / len(forced), 4),
            "policy_hit_rate": round(share, 4),
            "draw_changes_with_server_secret": rotated != sampled,
        }
    finally:
        settings.ip_hash_secret = original


async def _committed_revision(redis: Redis, turn_id: str) -> int | None:
    digest = hmac.new(
        SHADOW_SECRET.encode(), ("analyst-session:" + turn_id).encode(), hashlib.sha256
    ).hexdigest()
    revision = await redis.hget(f"analyst:{{{digest}}}", "revision")
    return int(revision) if revision is not None else None


async def probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="shadow-isolation-") as directory:
        runtime = await LiveShadowRuntime(Path(directory)).start()
        redis = Redis.from_url(f"redis://127.0.0.1:{runtime.redis_port}/0", socket_timeout=2)
        try:
            async with httpx.AsyncClient(base_url=runtime.base_url, timeout=60) as client:
                started = time.monotonic()
                response = await client.post(
                    "/analysis/query", json=PAYLOAD, headers={"x-request-id": "probe-blocked"}
                )
                elapsed = time.monotonic() - started
                body = response.json()
                provider = runtime.provider
                entered = provider.entered.wait(timeout=15)
                result = {
                    "status": response.status_code,
                    "response_seconds": round(elapsed, 3),
                    "provider_entered": entered,
                    "provider_in_flight_at_response": provider.in_flight,
                    "provider_released_at_response": provider.release.is_set(),
                    "citations": len(body.get("citations") or []),
                    "answer": body.get("answer"),
                    "answer_has_expected_average_25": "25" in (body.get("answer") or ""),
                    "route": body.get("route"),
                    "degraded": body.get("degraded"),
                    "warnings": body.get("warnings"),
                    "state_committed": body.get("state_committed"),
                    "revision": body.get("revision"),
                    "committed_revision_while_blocked": await _committed_revision(redis, TURN),
                }
                provider.release.set()
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if provider.in_flight == 0:
                        break
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.5)
                trial_requests = provider.requests
                replay = await client.post(
                    "/analysis/query", json=PAYLOAD, headers={"x-request-id": "probe-replay"}
                )
                await asyncio.sleep(0.5)
                result.update(
                    {
                        "trial_provider_requests": trial_requests,
                        "replay_identical": replay.json() == body,
                        "replay_revision": replay.json().get("revision"),
                        "replay_added_provider_requests": provider.requests - trial_requests,
                    }
                )
                return result
        finally:
            await redis.aclose()
            runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if shutil.which("redis-server") is None:
        raise SystemExit("redis-server is required for the shadow isolation probe")
    report = {
        "delivery": asyncio.run(probe()),
        "sampling": _steering_measurement(),
        "recipe": {
            "probe": "uv run --package knicksiq-api python tools/release/shadow_isolation_probe.py "
            "--out release-artifacts/production-readiness-20261030/shadow-isolation.json",
            "protocol_tests": "uv run --package knicksiq-api pytest "
            "apps/api/app/tests/test_shadow_isolation.py "
            "apps/api/app/tests/test_shadow_live_delivery.py",
            "runtime": "own uvicorn process, own sqlite database, own redis-server, fake "
            "OpenAI-compatible endpoint on 127.0.0.1; no paid provider and no .env",
        },
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if arguments.out:
        arguments.out.write_text(text + "\n")


if __name__ == "__main__":
    main()
