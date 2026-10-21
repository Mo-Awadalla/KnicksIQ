"""Measure live llm_primary provider cost, tokens, calls and latency per question.

Runs a deterministic round-robin sample through the in-process FastAPI app with the real
OpenRouter provider, one question at a time, and records the charged monthly-ledger delta for each
question. The ledger delta is authoritative because reserve() and settle() are what the cutoff
enforces; the provider's reported usage is recorded beside it as a cross-check.

    uv run --package knicksiq-api python tools/release/measure_llm_capacity.py \
        --questions 40 --out capacity.json

Requires a restored active release, Redis, and provider credentials in the environment. It never
contacts Qdrant and never changes the cutoff. A missing monthly ledger starts at zero in code.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import os
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"


class UsageCapture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.calls.clear()

    def attach(self, adapter: Any) -> None:
        original = adapter.generate

        async def wrapped(*, system: str, user: str) -> str:
            entry: dict[str, Any] = {
                "cost_usd": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "latency_ms": None,
                "error": None,
            }
            started = time.monotonic()
            try:
                raw = await original(system=system, user=user)
                metadata = getattr(adapter, "last_metadata", {}) or {}
                usage = metadata.get("usage") or {}
                entry.update(
                    {
                        "cost_usd": usage.get("cost"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    }
                )
                return raw
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised to the loop
                entry["error"] = type(exc).__name__
                raise
            finally:
                entry["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
                self.calls.append(entry)

        adapter.generate = wrapped


def sample_round_robin(limit: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    rows = [row for row in rows if row.get("category") != "follow_ups"]
    buckets: dict[str, list[dict[str, Any]]] = collections.OrderedDict()
    for row in rows:
        buckets.setdefault(row["category"], []).append(row)
    picked: list[dict[str, Any]] = []
    offset = 0
    while len(picked) < limit and any(offset < len(items) for items in buckets.values()):
        for items in buckets.values():
            if offset < len(items) and len(picked) < limit:
                picked.append(items[offset])
        offset += 1
    return picked


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def summarize(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    charged = [row["charged_usd"] for row in rows if row["charged_usd"] is not None]
    reported = [row["reported_cost_usd"] for row in rows if row["reported_cost_usd"] is not None]
    latencies = [row["latency_ms"] for row in rows]
    tokens = sum(row["total_tokens"] or 0 for row in rows)
    calls = sum(row["provider_calls"] for row in rows)
    mean_charged = statistics.mean(charged) if charged else None
    mean_reported = statistics.mean(reported) if reported else None
    p50_charged = statistics.median(charged) if charged else None
    p95_charged = percentile(charged, 0.95)
    production_cutoff = meta["production_cutoff_usd"]
    budget_rows: dict[str, int | None] = {}
    if mean_charged and mean_charged > 0:
        budget_rows["mean"] = math.floor(production_cutoff / mean_charged)
    if p50_charged and p50_charged > 0:
        budget_rows["p50"] = math.floor(production_cutoff / p50_charged)
    if p95_charged and p95_charged > 0:
        budget_rows["p95"] = math.floor(production_cutoff / p95_charged)
    by_category: dict[str, dict[str, Any]] = {}
    for category in dict.fromkeys(row["category"] for row in rows):
        group = [row for row in rows if row["category"] == category]
        group_charged = [row["charged_usd"] for row in group if row["charged_usd"] is not None]
        by_category[category] = {
            "questions": len(group),
            "validated": sum(bool(row["llm_validated"]) for row in group),
            "provider_calls": sum(row["provider_calls"] for row in group),
            "mean_charged_usd": round(statistics.mean(group_charged), 8) if group_charged else None,
            "p50_latency_ms": round(statistics.median([row["latency_ms"] for row in group]), 1),
        }
    return {
        **meta,
        "questions_attempted": len(rows),
        "http_200": sum(row["status_code"] == 200 for row in rows),
        "non_200": sum(row["status_code"] != 200 for row in rows),
        "llm_validated": sum(bool(row["llm_validated"]) for row in rows),
        "degraded": sum(bool(row["degraded"]) for row in rows),
        "provider_calls": calls,
        "calls_per_question_mean": round(calls / len(rows), 2) if rows else None,
        "charged_usd_total": round(sum(charged), 8),
        "reported_cost_usd_total": round(sum(reported), 8) if reported else None,
        "reported_cost_missing_calls": sum(
            1 for row in rows for call in row["calls"] if call["cost_usd"] is None
        ),
        "charged_usd_mean": round(mean_charged, 8) if mean_charged is not None else None,
        "charged_usd_p50": round(p50_charged, 8) if p50_charged is not None else None,
        "charged_usd_p95": round(p95_charged, 8) if p95_charged is not None else None,
        "reported_cost_usd_mean": round(mean_reported, 8) if mean_reported is not None else None,
        "tokens_total": tokens,
        "tokens_per_question_mean": round(tokens / len(rows), 1) if rows else None,
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p95": round(percentile(latencies, 0.95), 1) if latencies else None,
        "latency_ms_max": round(max(latencies), 1) if latencies else None,
        "budget_questions_at_production_cutoff": budget_rows,
        "by_category": by_category,
    }


async def run(limit: int, production_cutoff: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.core.config import get_settings
    from app.services import analyst_provider
    from redis.asyncio import from_url

    settings = get_settings()
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    redis = from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None

    async def ledger_total() -> float:
        if redis is None:
            return 0.0
        raw = await redis.get(key)
        return float(raw) if raw is not None else 0.0

    capture = UsageCapture()
    real_get_adapter = analyst_provider.get_llm_adapter

    def factory(*args: Any, **kwargs: Any) -> Any:
        adapter = real_get_adapter(*args, **kwargs)
        capture.attach(adapter)
        return adapter

    analyst_provider.get_llm_adapter = factory
    selected = sample_round_robin(limit)
    ledger_start = await ledger_total()
    rows: list[dict[str, Any]] = []
    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="https://api.knicksiq.win", timeout=90.0
            ) as client:
                for row in selected:
                    capture.clear()
                    before = await ledger_total()
                    started = time.monotonic()
                    status_code = 0
                    body: dict[str, Any] = {}
                    try:
                        response = await client.post(
                            "/analysis/query",
                            json={
                                "question": row["question"],
                                "season": "2025-26",
                                "turn_id": "capacity-" + uuid.uuid4().hex,
                                "expected_revision": 0,
                            },
                        )
                        status_code = response.status_code
                        body = response.json() if status_code == 200 else {}
                    finally:
                        elapsed = (time.monotonic() - started) * 1000
                    after = await ledger_total()
                    calls = [dict(call) for call in capture.calls]
                    reported = sum(
                        call["cost_usd"] for call in calls if call["cost_usd"] is not None
                    )
                    rows.append(
                        {
                            "id": row["id"],
                            "category": row["category"],
                            "answerable": row.get("answerable"),
                            "status_code": status_code,
                            "llm_validated": bool(body.get("llm_validated")),
                            "degraded": bool(body.get("degraded")),
                            "warnings": body.get("warnings") or [],
                            "citations": len(body.get("citations") or []),
                            "answer_chars": len(body.get("answer") or ""),
                            "data_version": body.get("data_version"),
                            "provider_calls": len(calls),
                            "reported_cost_usd": round(reported, 8) if calls else 0.0,
                            "charged_usd": round(after - before, 8),
                            "prompt_tokens": sum(call["prompt_tokens"] or 0 for call in calls),
                            "completion_tokens": sum(
                                call["completion_tokens"] or 0 for call in calls
                            ),
                            "total_tokens": sum(call["total_tokens"] or 0 for call in calls),
                            "latency_ms": round(elapsed, 1),
                        }
                    )
        ledger_end = await ledger_total()
    finally:
        analyst_provider.get_llm_adapter = real_get_adapter
        if redis is not None:
            await redis.aclose()

    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "In-process ASGI app, real OpenRouter provider, restored active release, "
        "Qdrant disabled, sequential single client.",
        "provider": settings.ai_provider,
        "base_url_host": settings.ai_base_url.split("/")[2]
        if "://" in settings.ai_base_url
        else "",
        "model": settings.ai_chat_model,
        "answer_mode": settings.analysis_answer_mode,
        "test_cutoff_usd": settings.openrouter_monthly_cutoff_usd,
        "production_cutoff_usd": production_cutoff,
        "ledger_key": key,
        "ledger_start_usd": round(ledger_start, 8),
        "ledger_end_usd": round(ledger_end, 8),
        "ledger_delta_usd": round(ledger_end - ledger_start, 8),
        "data_version": rows[0].get("data_version") if rows else None,
    }
    return summarize(rows, meta), rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=40)
    parser.add_argument("--production-cutoff", type=float, default=2.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary, rows = asyncio.run(run(args.questions, args.production_cutoff))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rows_path = args.out.with_suffix(".rows.jsonl")
    rows_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, dict)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
