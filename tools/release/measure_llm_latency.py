"""Measure live llm_primary latency by stage and quality on a fixed 40-question sample.

The response trace (prepare, resolve, tools, each provider call with tokens and HTTP TTFB,
review) supplies the stage table.

Usage:
    uv run --package knicksiq-api python tools/release/measure_llm_latency.py \
        --out docs/release-evidence/llm-primary-20261021/latency/base.json --trials 1
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
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

import analyst_live_e2e as e2e  # noqa: E402  (same directory; reuses classify/meets_expectation)
from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"

STAGE_ORDER = (
    "session_and_release",
    "archive_records",
    "query_resolution",
    "plan",
    "tool",
    "answer",
    "review",
    "repair",
    "other",
)


class UsageCapture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.calls.clear()

    def attach(self, adapter: Any, role: str) -> None:
        original = adapter.generate

        async def wrapped(*, system: str, user: str) -> str:
            entry: dict[str, Any] = {"role": role, "status": None}
            started = time.monotonic()
            try:
                raw = await original(system=system, user=user)
                entry["status"] = "ok"
                return raw
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised to the loop
                entry["status"] = type(exc).__name__
                entry["error"] = str(exc)[:800]
                raise
            finally:
                metadata = getattr(adapter, "last_metadata", {}) or {}
                usage = metadata.get("usage") or {}
                details = usage.get("completion_tokens_details") or {}
                entry.update(
                    {
                        "latency_ms": round((time.monotonic() - started) * 1000, 1),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                        "reasoning_tokens": details.get("reasoning_tokens"),
                        "finish_reason": metadata.get("finish_reason"),
                        "content_kind": metadata.get("content_kind"),
                        "reasoning_chars": metadata.get("reasoning_chars"),
                        "http_ttfb_ms": metadata.get("http_ttfb_ms"),
                        "request_bytes": metadata.get("request_bytes"),
                        "response_bytes": metadata.get("response_bytes"),
                        "provider": metadata.get("provider"),
                        "max_tokens": metadata.get("max_tokens"),
                    }
                )
                self.calls.append(entry)

        adapter.generate = wrapped


class FailureCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "analyst_execution_failed" in message:
            self.records.append(
                {
                    "error_type": getattr(record, "error_type", None),
                    "stage": getattr(record, "stage", None),
                    "message": message[:800],
                }
            )


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
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def bucket(entry: dict[str, Any]) -> str:
    stage = entry.get("stage")
    if stage == "prepare":
        return entry.get("tool") if entry.get("tool") in STAGE_ORDER else "other"
    if stage == "tool":
        return "tool"
    if stage == "review":
        return "review"
    if stage == "revise":
        return "repair"
    if stage == "orchestrate":
        return "plan" if entry.get("action") == "call_tools" else "answer"
    return "other"


def stages_of(trace: list[dict[str, Any]]) -> dict[str, float]:
    totals = dict.fromkeys(STAGE_ORDER, 0.0)
    for entry in trace:
        name = bucket(entry)
        totals[name] += float(entry.get("latency_ms") or 0)
    return {key: round(value, 1) for key, value in totals.items()}


def stage_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [row["stages"][field] for row in rows]
    totals = [row["latency_ms"] for row in rows]
    table = {
        "questions_with_stage": sum(value > 0 for value in values),
        "mean_ms": round(statistics.mean(values), 1) if values else None,
        "p50_ms": round(statistics.median(values), 1) if values else None,
        "p95_ms": round(percentile(values, 0.95), 1) if values else None,
        "share_of_total_mean": None,
    }
    if totals and statistics.mean(totals) > 0:
        table["share_of_total_mean"] = round(statistics.mean(values) / statistics.mean(totals), 3)
    return table


def summarize(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    latency = [row["latency_ms"] for row in rows]
    calls = [call for row in rows for call in row["calls"]]
    per_call = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
    ttfb = [call["http_ttfb_ms"] for call in calls if call.get("http_ttfb_ms") is not None]
    prompt = sum(call.get("prompt_tokens") or 0 for call in calls)
    completion = sum(call.get("completion_tokens") or 0 for call in calls)
    by_category: dict[str, Any] = {}
    for category in dict.fromkeys(row["category"] for row in rows):
        group = [row for row in rows if row["category"] == category]
        group_latency = [row["latency_ms"] for row in group]
        by_category[category] = {
            "questions": len(group),
            "met": sum(row["meets_expectation"] for row in group),
            "p50_latency_ms": round(statistics.median(group_latency), 1),
            "p95_latency_ms": round(percentile(group_latency, 0.95), 1),
            "provider_calls": sum(len(row["calls"]) for row in group),
        }
    providers = collections.Counter(
        str(call.get("provider")) for call in calls if call.get("provider")
    )
    empty_calls = [call for call in calls if "omitted message content" in (call.get("error") or "")]
    by_call_stage: dict[str, Any] = {}
    for stage in ("plan", "answer", "review", "repair", "other"):
        group = [call for call in calls if call.get("stage") == stage]
        latencies = [call["latency_ms"] for call in group if call.get("latency_ms") is not None]
        stage_empty = sum(
            1 for call in group if "omitted message content" in (call.get("error") or "")
        )
        by_call_stage[stage] = {
            "calls": len(group),
            "empty_content": stage_empty,
            "empty_rate": round(stage_empty / len(group), 3) if group else None,
            "p50_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
            "p95_latency_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
            "max_tokens_seen": sorted(
                {call.get("max_tokens") for call in group},
                key=lambda value: (value is None, value),
            ),
        }
    return {
        **meta,
        "questions": len(rows),
        "trials": sorted({row["trial"] for row in rows}),
        "http_200": sum(row["status_code"] == 200 for row in rows),
        "non_200": sum(row["status_code"] != 200 for row in rows),
        "provider_calls": len(calls),
        "calls_per_question": round(len(calls) / len(rows), 2) if rows else None,
        "providers": dict(providers),
        "empty_content_calls": len(empty_calls),
        "empty_content_rate": round(len(empty_calls) / len(calls), 3) if calls else None,
        "empty_content_by_stage": by_call_stage,
        "finish_reasons": dict(
            collections.Counter(str(call.get("finish_reason")) for call in calls)
        ),
        "content_kinds": dict(collections.Counter(str(call.get("content_kind")) for call in calls)),
        "reasoning_tokens_total": sum(call.get("reasoning_tokens") or 0 for call in calls),
        "contexts_with_reasoning_tokens": sum(bool(call.get("reasoning_tokens")) for call in calls),
        "call_latency_ms_p50": round(statistics.median(per_call), 1) if per_call else None,
        "call_latency_ms_p95": round(percentile(per_call, 0.95), 1) if per_call else None,
        "call_ttfb_ms_p50": round(statistics.median(ttfb), 1) if ttfb else None,
        "call_ttfb_ms_p95": round(percentile(ttfb, 0.95), 1) if ttfb else None,
        "prompt_tokens_total": prompt,
        "completion_tokens_total": completion,
        "prompt_tokens_per_question": round(prompt / len(rows), 1) if rows else None,
        "completion_tokens_per_question": round(completion / len(rows), 1) if rows else None,
        "latency_ms_p50": round(statistics.median(latency), 1) if latency else None,
        "latency_ms_mean": round(statistics.mean(latency), 1) if latency else None,
        "latency_ms_p95": round(percentile(latency, 0.95), 1) if latency else None,
        "latency_ms_max": round(max(latency), 1) if latency else None,
        "latency_ms_min": round(min(latency), 1) if latency else None,
        "latency_ms_spread": round(max(latency) - min(latency), 1) if latency else None,
        "meets_expectation": sum(row["meets_expectation"] for row in rows),
        "meets_expectation_rate": round(
            sum(row["meets_expectation"] for row in rows) / len(rows), 3
        )
        if rows
        else None,
        "validated": sum(row["outcome"].startswith("validated") for row in rows),
        "validated_declined": sum(row["outcome"] == "validated_declined" for row in rows),
        "degraded": sum(row["outcome"].startswith("fallback") for row in rows),
        "outcomes": dict(collections.Counter(row["outcome"] for row in rows)),
        "stage_table": {name: stage_summary(rows, name) for name in STAGE_ORDER},
        "overhead": {
            "mean_ms": round(statistics.mean(row["overhead_ms"] for row in rows), 1)
            if rows
            else None,
            "p50_ms": round(statistics.median([row["overhead_ms"] for row in rows]), 1)
            if rows
            else None,
            "p95_ms": round(percentile([row["overhead_ms"] for row in rows], 0.95), 1)
            if rows
            else None,
        },
        "by_category": by_category,
    }


async def clear_answer_cache() -> None:
    from app.core.config import get_settings
    from redis.asyncio import Redis

    settings = get_settings()
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        keys = [key async for key in redis.scan_iter(match="answer:*", count=500)]
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def run(
    limit: int, trials: int, checkpoint: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.core.config import get_settings
    from app.services import analyst_provider
    from redis.asyncio import Redis

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"

    async def ledger_total() -> float:
        raw = await redis.get(key)
        return float(raw) if raw is not None else 0.0

    capture = UsageCapture()
    real_get_adapter = analyst_provider.get_llm_adapter

    def factory(*args: Any, **kwargs: Any) -> Any:
        adapter = real_get_adapter(*args, **kwargs)
        capture.attach(adapter, "analyst")
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
                for trial in range(trials):
                    await clear_answer_cache()
                    for row in selected:
                        capture.clear()
                        failures = FailureCapture()
                        root = logging.getLogger()
                        root.addHandler(failures)
                        started = time.monotonic()
                        status_code = 0
                        body: dict[str, Any] = {}
                        response = None
                        try:
                            response = await client.post(
                                "/analysis/query",
                                json={
                                    "question": row["question"],
                                    "season": "2025-26",
                                    "turn_id": "latency-" + uuid.uuid4().hex,
                                    "expected_revision": 0,
                                },
                            )
                            status_code = response.status_code
                            body = response.json() if status_code == 200 else {}
                        finally:
                            elapsed = (time.monotonic() - started) * 1000
                            root.removeHandler(failures)
                        if status_code != 200 and response is not None:
                            print("NON200", row["id"], status_code, response.text[:500])
                        trace = body.get("tool_calls") or []
                        stages = stages_of(trace)
                        accounted = sum(value for value in stages.values())
                        outcome = (
                            e2e.classify(body, failures.records) if body else f"http_{status_code}"
                        )
                        model_stages = [
                            entry
                            for entry in trace
                            if entry.get("stage") in {"orchestrate", "review", "revise"}
                        ]
                        calls = [dict(call) for call in capture.calls]
                        for call, entry in zip(calls, model_stages, strict=False):
                            call["stage"] = bucket(entry)
                            call["action"] = entry.get("action")
                        empty = [
                            call
                            for call in calls
                            if "omitted message content" in (call.get("error") or "")
                        ]
                        row_out = {
                            "trial": trial,
                            "id": row["id"],
                            "category": row["category"],
                            "answerable": row["answerable"],
                            "status_code": status_code,
                            "latency_ms": round(elapsed, 1),
                            "stages": stages,
                            "overhead_ms": round(max(0.0, elapsed - accounted), 1),
                            "trace": trace,
                            "calls": calls,
                            "empty_content_calls": len(empty),
                            "outcome": outcome,
                            "failure_records": failures.records,
                            "meets_expectation": e2e.meets_expectation(row, outcome),
                            "answer": body.get("answer") or "",
                            "warnings": body.get("warnings") or [],
                            "citations": len(body.get("citations") or []),
                            "provider_calls": len(calls),
                            "degraded": bool(body.get("degraded")),
                            "validator": bool(body.get("llm_validated")),
                            "data_version": body.get("data_version"),
                        }
                        rows.append(row_out)
                        if checkpoint is not None:
                            checkpoint.parent.mkdir(parents=True, exist_ok=True)
                            with checkpoint.open("a") as handle:
                                handle.write(json.dumps(row_out, sort_keys=True) + "\n")
        ledger_end = await ledger_total()
    finally:
        analyst_provider.get_llm_adapter = real_get_adapter
        await redis.aclose()

    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "In-process ASGI app, real OpenRouter provider, restored active release, "
        "llm_primary evidence loop, sequential single client, no answer cache.",
        "provider": settings.ai_provider,
        "model": settings.ai_chat_model,
        "answer_mode": settings.analysis_answer_mode,
        "evidence_loop": settings.analyst_evidence_loop_enabled,
        "reasoning_effort": settings.ai_reasoning_effort,
        "request_timeout_seconds": settings.ai_request_timeout_seconds,
        "ledger_key": key,
        "ledger_start_usd": round(ledger_start, 8),
        "ledger_end_usd": round(ledger_end, 8),
        "ledger_delta_usd": round(ledger_end - ledger_start, 8),
        "sample": [row["id"] for row in selected],
        "data_version": rows[0].get("data_version") if rows else None,
    }
    return summarize(rows, meta), rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=40)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    checkpoint = args.out.with_suffix(".rows.jsonl")
    if checkpoint.exists():
        checkpoint.unlink()
    summary, rows = asyncio.run(run(args.questions, args.trials, checkpoint))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    args.out.with_suffix(".rows.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "trace"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
