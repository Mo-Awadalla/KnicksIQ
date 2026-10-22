"""Infrastructure adversarial phases: budget, provider faults, rate limits, proxy, cache."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from adversarial_support import (
    FaultAdapter,
    adapter_override,
    ask,
    body_of,
    clear_limits,
    client_for,
    ledger_value,
    no_leak,
    restore_ledger,
)


async def phase_budget(h):
    from app.services.analyst_budget import BudgetReservation

    old_ledger = await ledger_value(h)
    old_cutoff = h.settings.openrouter_monthly_cutoff_usd
    await h.redis.set(h.ledger_key, "2")
    h.settings.openrouter_monthly_cutoff_usd = 2.0
    try:
        await ask(
            h,
            "budget-cutoff",
            "T17 monthly cutoff",
            "How many points did the Knicks score in their last game?",
            "200 degraded deterministic answer with 94 points, no provider call",
            lambda r, b, c, lat: (
                r.status_code == 200
                and b.get("degraded") is True
                and b.get("llm_validated") is False
                and "94" in (b.get("answer") or "")
                and bool(b.get("citations"))
                and c == 0
                and lat < 2000
                and b.get("data_version") != "unreleased",
                f"status={r.status_code} calls={c} latency_ms={lat}",
            ),
            turn_id="safety-cutoff-" + uuid.uuid4().hex,
        )
        unchanged = await ledger_value(h)
        h.add(
            "budget-cutoff-no-charge",
            "T17 monthly cutoff",
            "Rejected reservation does not change the ledger",
            None,
            float(unchanged) == 2.0,
            f"ledger={unchanged}",
        )
    finally:
        h.settings.openrouter_monthly_cutoff_usd = old_cutoff
        await restore_ledger(h, old_ledger)
    old_ledger = await ledger_value(h)
    old_cutoff = h.settings.openrouter_monthly_cutoff_usd
    await h.redis.set(h.ledger_key, "0")
    h.settings.openrouter_monthly_cutoff_usd = 0.05
    try:
        reservations = await asyncio.gather(*(BudgetReservation.reserve(0.01) for _ in range(10)))
        accepted = [item for item in reservations if item is not None]
        for item in accepted:
            await item.settle(0.01)
        ledger = float(await ledger_value(h))
        h.add(
            "budget-concurrent",
            "T18 concurrent ledger",
            "Exactly five of ten parallel 0.01 reservations fit a 0.05 cap",
            None,
            len(accepted) == 5 and abs(ledger - 0.05) < 1e-9,
            f"accepted={len(accepted)} ledger={ledger}",
        )
    finally:
        h.settings.openrouter_monthly_cutoff_usd = old_cutoff
        await restore_ledger(h, old_ledger)
        await h.redis.delete(h.ledger_key + ":reservations")
    old_ledger = await ledger_value(h)
    try:
        await h.redis.delete(h.ledger_key)
        reservation = await BudgetReservation.reserve(0.01)
        created = await ledger_value(h)
        if reservation is not None:
            await reservation.settle(0.0)
        h.add(
            "budget-absent-ledger",
            "T17 ledger loss",
            "A missing ledger starts at zero and accepts a reservation",
            None,
            reservation is not None and created is not None,
            f"accepted={reservation is not None} ledger={created}",
        )
    finally:
        await restore_ledger(h, old_ledger)
    import app.services.analyst_budget as budget_module

    original = budget_module._redis

    async def unavailable():
        return None

    budget_module._redis = unavailable
    try:
        await ask(
            h,
            "budget-redis-down",
            "T19 Redis outage",
            "How many points did the Knicks score in their last game?",
            "200 degraded deterministic answer, no provider call",
            lambda r, b, c, lat: (
                r.status_code == 200
                and b.get("degraded") is True
                and b.get("llm_validated") is False
                and "94" in (b.get("answer") or "")
                and bool(b.get("citations"))
                and c == 0,
                f"status={r.status_code} calls={c} latency_ms={lat}",
            ),
            turn_id="safety-redis-down-" + uuid.uuid4().hex,
        )
    finally:
        budget_module._redis = original


async def phase_provider(h):
    from app.services import analyst_provider

    question = "How many points did the Knicks score in their last game?"
    for cid, mode, limit in (
        ("provider-outage", "outage", 5000),
        ("provider-garbage", "garbage", 5000),
    ):
        before = await ledger_value(h)
        with adapter_override(analyst_provider, lambda mode=mode: FaultAdapter(mode)) as calls:
            started = time.monotonic()
            response = await h.client.post(
                "/analysis/query",
                json={
                    "question": question,
                    "season": "2025-26",
                    "turn_id": "safety-" + cid + "-" + uuid.uuid4().hex,
                },
            )
            latency = round((time.monotonic() - started) * 1000)
        await restore_ledger(h, before)
        passed, detail = no_leak(response, body_of(response), calls["n"], latency)
        h.add(
            cid,
            "T09 and T20 provider fault",
            f"200 degraded factual answer within {limit} ms, no error text",
            response,
            passed and latency < limit,
            detail,
            latency_ms=latency,
            provider_calls=calls["n"],
        )
    before = await ledger_value(h)
    with adapter_override(analyst_provider, lambda: FaultAdapter("timeout")) as calls:
        started = time.monotonic()
        response = await h.client.post(
            "/analysis/query",
            json={
                "question": question,
                "season": "2025-26",
                "turn_id": "safety-provider-timeout-" + uuid.uuid4().hex,
            },
        )
        latency = round((time.monotonic() - started) * 1000)
    await restore_ledger(h, before)
    passed, detail = no_leak(response, body_of(response), calls["n"], latency)
    ok = passed and 18000 <= latency <= 26000
    h.add(
        "provider-timeout",
        "T20 hung provider",
        "200 degraded factual answer between 18 and 26 seconds",
        response,
        ok,
        detail,
        latency_ms=latency,
        provider_calls=calls["n"],
        status="pass" if ok else "open",
    )


async def phase_rate(h):
    from app.api import analysis_policy
    from app.services.runtime_store import enforce_redis_limits

    old_minute = h.settings.public_chat_rate_limit_per_minute
    old_day = h.settings.public_chat_rate_limit_per_day
    h.settings.public_chat_rate_limit_per_minute = 2
    h.settings.public_chat_rate_limit_per_day = 100000
    try:
        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()
        ip = "198.18.0.10"
        await clear_limits(h, ip)
        client = client_for(h.app, ip)
        try:
            statuses = []
            for _ in range(3):
                response = await client.post("/analysis/query", json={"question": "hi"})
                statuses.append(response.status_code)
        finally:
            await client.aclose()
        other_ip = "198.18.0.11"
        await clear_limits(h, other_ip)
        other = client_for(h.app, other_ip)
        try:
            other_status = (
                await other.post("/analysis/query", json={"question": "hi"})
            ).status_code
        finally:
            await other.aclose()
        h.add(
            "rate-inmemory",
            "T16 rate limiting",
            "Third request from one client is 429; another client is not blocked",
            None,
            statuses == [200, 200, 429] and other_status == 200,
            f"statuses={statuses} other={other_status}",
        )
        for value in (ip, other_ip):
            await clear_limits(h, value)
        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()
        spoof_ip = "198.18.0.12"
        await clear_limits(h, spoof_ip)
        spoof = client_for(h.app, spoof_ip)
        try:
            spoofed = []
            for index in range(3):
                response = await spoof.post(
                    "/analysis/query",
                    json={"question": "hi"},
                    headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
                )
                spoofed.append(response.status_code)
        finally:
            await spoof.aclose()
        h.add(
            "rate-xff",
            "T15 forwarded header spoofing",
            "Rotating X-Forwarded-For does not create new identities",
            None,
            spoofed == [200, 200, 429],
            f"statuses={spoofed}",
        )
        await clear_limits(h, spoof_ip)
        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()
        hash_value = "safety-rate-" + uuid.uuid4().hex
        results = []
        for _ in range(3):
            try:
                results.append(await enforce_redis_limits(hash_value))
            except ValueError as exc:
                results.append(str(exc))
        await h.redis.delete(f"limit:minute:{hash_value}", f"limit:day:{hash_value}")
        h.add(
            "rate-redis",
            "T16 Redis limiter",
            "Third Redis count raises the minute limit",
            None,
            results == [False, False, "minute"],
            f"results={results}",
        )
    finally:
        h.settings.public_chat_rate_limit_per_minute = old_minute
        h.settings.public_chat_rate_limit_per_day = old_day
        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()


async def phase_proxy(h):
    import yaml
    from httpx import ASGITransport, AsyncClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    blueprint = yaml.safe_load(Path("render.yaml").read_text())
    api = next(item for item in blueprint["services"] if item["name"] == "knicksiq-api")
    env = {item["key"]: item.get("value") for item in api["envVars"]}
    secret = next(item for item in api["envVars"] if item["key"] == "IP_HASH_SECRET")
    h.add(
        "config-render",
        "T23 production configuration",
        "Secret, CORS, host and cutoff values are production-safe",
        None,
        secret.get("generateValue") is True
        and env.get("OPENROUTER_MONTHLY_CUTOFF_USD") == "2"
        and "https://www.knicksiq.win" in (env.get("CORS_ORIGINS") or "")
        and "api.knicksiq.win" in (env.get("TRUSTED_HOSTS") or ""),
        f"secret_generated={secret.get('generateValue')} "
        f"cutoff={env.get('OPENROUTER_MONTHLY_CUTOFF_USD')}",
    )
    trusted = env.get("FORWARDED_ALLOW_IPS") or "127.0.0.1"
    h.add(
        "config-forwarded-allow-ips",
        "T16 Render proxy trust",
        "render.yaml trusts the Render private proxy range",
        None,
        "10.0.0.0/8" in trusted and "127.0.0.1" in trusted,
        f"FORWARDED_ALLOW_IPS={trusted!r}",
    )
    wrapped = ProxyHeadersMiddleware(h.app, trusted_hosts=trusted)
    transport = ASGITransport(app=wrapped, raise_app_exceptions=False, client=("10.0.0.5", 443))
    async with AsyncClient(
        transport=transport, base_url="http://api.knicksiq.win", timeout=60
    ) as client:
        redirect = await client.post(
            "/analysis/query",
            json={"question": "hi"},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.1"},
        )
    h.add(
        "proxy-https",
        "T16 HTTPS redirect behind the proxy",
        "Forwarded https reaches the app instead of a 307 redirect",
        redirect,
        redirect.status_code == 200,
        f"status={redirect.status_code} trusted={trusted!r}",
    )
    old_minute = h.settings.public_chat_rate_limit_per_minute
    h.settings.public_chat_rate_limit_per_minute = 1
    try:
        from app.api import analysis_policy

        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()
        for ip in ("198.51.100.1", "198.51.100.2"):
            await clear_limits(h, ip)
        transport = ASGITransport(app=wrapped, raise_app_exceptions=False, client=("10.0.0.5", 443))
        async with AsyncClient(
            transport=transport, base_url="https://api.knicksiq.win", timeout=60
        ) as client:
            first = await client.post(
                "/analysis/query",
                json={"question": "hi"},
                headers={"X-Forwarded-For": "198.51.100.1"},
            )
            second = await client.post(
                "/analysis/query",
                json={"question": "hi"},
                headers={"X-Forwarded-For": "198.51.100.2"},
            )
        h.add(
            "proxy-client-identity",
            "T16 per-client rate limiting",
            "Two forwarded clients get independent rate-limit buckets",
            second,
            first.status_code == 200 and second.status_code == 200,
            f"first={first.status_code} second={second.status_code}",
        )
    finally:
        h.settings.public_chat_rate_limit_per_minute = old_minute
        from app.api import analysis_policy

        analysis_policy._requests_by_client.clear()
        analysis_policy._daily_requests_by_client.clear()
        for ip in ("198.51.100.1", "198.51.100.2"):
            await clear_limits(h, ip)


async def phase_cache(h):
    from app.services.runtime_store import answer_cache_key

    base = dict(
        question="How many points did the Knicks score in their last game?",
        data_version="2025-26.20260928.1",
        model_version="deepseek/deepseek-v4.1-flash",
        season="2025-26",
        answer_mode="llm_primary",
        prompt_version="v1",
        index_version="2025-26.20260928.1",
    )
    first = answer_cache_key(**base)
    same = answer_cache_key(**base)
    variants = [
        answer_cache_key(**{**base, "data_version": "2025-26.20261021.1"}),
        answer_cache_key(**{**base, "index_version": "2025-26.20261021.1"}),
        answer_cache_key(**{**base, "model_version": "other/model"}),
        answer_cache_key(**{**base, "answer_mode": "deterministic"}),
        answer_cache_key(**{**base, "prompt_version": "v2"}),
        answer_cache_key(**{**base, "season": "2024-25"}),
    ]
    h.add(
        "cache-key-isolation",
        "T21 cache poisoning",
        "Release, index, model, mode, prompt and season all change the key",
        None,
        first == same and all(value != first for value in variants) and len(set(variants)) == 6,
        f"variants={len(set(variants))}",
    )
    import app.api.analysis as analysis_module

    old_mode = h.settings.analysis_answer_mode
    old_loop = h.settings.analyst_evidence_loop_enabled
    old_planner = h.settings.rag_llm_planner_enabled
    original_get = analysis_module.get_cached_answer
    original_set = analysis_module.set_cached_answer

    async def stale_cache(_key):
        return {"answer": "STALE CACHED ANSWER", "degraded": True}

    async def no_cache(_key, _value):
        return None

    h.settings.analysis_answer_mode = "deterministic"
    h.settings.analyst_evidence_loop_enabled = False
    h.settings.rag_llm_planner_enabled = False
    analysis_module.get_cached_answer = stale_cache
    analysis_module.set_cached_answer = no_cache
    try:
        response = await h.client.post(
            "/analysis/query", json={"question": "What is the Knicks record this season?"}
        )
    finally:
        analysis_module.get_cached_answer = original_get
        analysis_module.set_cached_answer = original_set
        h.settings.analysis_answer_mode = old_mode
        h.settings.analyst_evidence_loop_enabled = old_loop
        h.settings.rag_llm_planner_enabled = old_planner
    h.add(
        "cache-degraded",
        "T21 degraded cache entry",
        "A degraded cached answer is ignored and recomputed",
        response,
        response.status_code == 200
        and "STALE CACHED ANSWER" not in (body_of(response).get("answer") or ""),
        f"status={response.status_code}",
    )
