"""Adversarial end-to-end checks for the public llm_primary analyst path.

Runs the in-process FastAPI app with production serialization against the local restored
release and the real provider. Infrastructure faults are injected in-process so the
artifact is repeatable and does not spend provider budget.

    uv run --package knicksiq-api python tools/release/analyst_adversarial_e2e.py \
      --out docs/release-evidence/llm-primary-20261021/safety/baseline.json \
      --env-file /path/to/repo/.env

Exit 0 when no case failed; open cases are reported separately.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import adversarial_phases_infra as infra
import adversarial_phases_public as public
import httpx
from adversarial_support import Harness, Tee, configure_env


async def run(env_file, out_path, phases="all"):
    configure_env(env_file)
    from app.core.config import get_settings
    from app.main import create_app
    from app.services import analyst_provider
    from app.services.runtime_store import _redis

    settings = get_settings()
    if settings.ai_provider != "openrouter" or not settings.ai_api_key:
        print("AI_API_KEY and AI_PROVIDER=openrouter are required", file=sys.stderr)
        return 2
    started_at = datetime.now(UTC).isoformat()
    real_stdout = sys.stdout
    tee = Tee(real_stdout)
    sys.stdout = tee
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            redis = await _redis()
            if redis is None:
                print("Redis db 4 is required", file=sys.stderr)
                return 2
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="https://api.knicksiq.win",
                timeout=60,
            )
            h = Harness(app, settings, client, redis, tee)
            original_adapter = analyst_provider.get_llm_adapter

            def counting(*args, **kwargs):
                h.calls += 1
                return original_adapter(*args, **kwargs)

            analyst_provider.get_llm_adapter = counting

            async def policy_first(harness):
                harness.trial = 1
                await public.phase_policy(harness)

            async def injections_first(harness):
                harness.trial = 1
                await public.phase_injections(harness)

            async def policy_second(harness):
                harness.trial = 2
                await public.phase_policy(harness)

            async def injections_second(harness):
                harness.trial = 2
                await public.phase_injections(harness)

            sequence = (
                ("http", public.phase_http),
                ("policy", policy_first),
                ("injections", injections_first),
                ("policy-t2", policy_second),
                ("injections-t2", injections_second),
                ("sessions", public.phase_sessions),
                ("budget", infra.phase_budget),
                ("provider", infra.phase_provider),
                ("rate", infra.phase_rate),
                ("proxy", infra.phase_proxy),
                ("cache", infra.phase_cache),
                ("errors", public.phase_errors),
            )
            requested = None if phases == "all" else set(phases.split(","))
            try:
                for name, phase in sequence:
                    if requested is not None and name not in requested:
                        continue
                    print(f"phase {name}", file=sys.stderr)
                    await phase(h)
            finally:
                h.trial = 1
                analyst_provider.get_llm_adapter = original_adapter
                await client.aclose()
                await redis.aclose()
    finally:
        sys.stdout = real_stdout
    summary = collections.Counter(item["status"] for item in h.cases)
    report = {
        "schema": "analyst-adversarial-e2e-v1",
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "environment": "production serialization, in-process ASGI",
        "release": "local restored 2025-26.20260928.1",
        "provider": "openrouter/deepseek/deepseek-v4.1-flash",
        "redis_db": 4,
        "live_questions": h.live,
        "provider_calls": h.calls,
        "summary": dict(summary),
        "cases": h.cases,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2), file=sys.stderr)
    return 0 if summary.get("fail", 0) == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--phases", default="all", help="Comma-separated phase names")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.env_file, args.out, args.phases)))


if __name__ == "__main__":
    main()
