"""Measure llm_primary latency, cost and validation per OpenRouter upstream.

Same 40-question round-robin sample as measure_llm_latency.py, run through the in-process app
with routing taken from settings. Every provider call records its upstream, cost, finish_reason
and JSON parse outcome. Usage is in the artifact README.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools/release"))

import analyst_live_e2e as e2e  # noqa: E402
from latency_stats import percentile  # noqa: E402

QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"


class UsageCapture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.calls.clear()

    def attach(self, adapter: Any, role: str) -> None:
        original = adapter.generate

        async def wrapped(*, system: str, user: str) -> str:
            entry: dict[str, Any] = {"role": role, "status": None, "json_ok": None}
            started = time.monotonic()
            try:
                raw = await original(system=system, user=user)
                entry["status"] = "ok"
                try:
                    json.loads(raw)
                    entry["json_ok"] = True
                except (TypeError, ValueError):
                    entry["json_ok"] = False
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
                        "provider": metadata.get("provider"),
                        "model": metadata.get("model"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "reasoning_tokens": details.get("reasoning_tokens"),
                        "cost_usd": usage.get("cost"),
                        "finish_reason": metadata.get("finish_reason"),
                        "content_kind": metadata.get("content_kind"),
                        "response_bytes": metadata.get("response_bytes"),
                        "http_ttfb_ms": metadata.get("http_ttfb_ms"),
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
        if "analyst_execution_failed" in record.getMessage():
            self.records.append(
                {
                    "error_type": getattr(record, "error_type", None),
                    "stage": getattr(record, "stage", None),
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


def summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
    costs = [call["cost_usd"] for call in calls if call.get("cost_usd") is not None]
    return {
        "calls": len(calls),
        "stages": dict(collections.Counter(call.get("stage") or "unmapped" for call in calls)),
        "mean_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "p50_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_latency_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
        "max_latency_ms": round(max(latencies), 1) if latencies else None,
        "mean_cost_usd": round(statistics.mean(costs), 8) if costs else None,
        "total_cost_usd": round(sum(costs), 8) if costs else None,
        "finish_reasons": dict(collections.Counter(str(c.get("finish_reason")) for c in calls)),
        "content_kinds": dict(collections.Counter(str(c.get("content_kind")) for c in calls)),
        "json_parse_ok": sum(1 for call in calls if call.get("json_ok")),
        "json_parse_failed": sum(1 for call in calls if call.get("json_ok") is False),
        "failed_calls": sum(1 for call in calls if call.get("status") != "ok"),
        "at_cap": sum(
            1
            for call in calls
            if call.get("finish_reason") == "length"
            and call.get("max_tokens") is not None
            and call.get("completion_tokens") == call.get("max_tokens")
        ),
    }


def summarize(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    latency = [row["latency_ms"] for row in rows]
    calls = [call for row in rows for call in row["calls"]]
    providers: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for call in calls:
        providers[str(call.get("provider"))].append(call)
    per_upstream = {
        provider: summarize_calls(group)
        for provider, group in sorted(providers.items(), key=lambda item: -len(item[1]))
    }
    by_answer_provider: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("answer_provider"))
        bucket = by_answer_provider.setdefault(
            key, {"questions": 0, "validated": 0, "meets_expectation": 0, "cost_usd": 0.0}
        )
        bucket["questions"] += 1
        bucket["validated"] += int(row["validated"])
        bucket["meets_expectation"] += int(row["meets_expectation"])
        bucket["cost_usd"] = round(bucket["cost_usd"] + (row.get("cost_usd") or 0.0), 8)
    by_review_provider: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("review_provider") is None:
            continue
        key = str(row.get("review_provider"))
        bucket = by_review_provider.setdefault(key, {"questions": 0, "validated": 0})
        bucket["questions"] += 1
        bucket["validated"] += int(row["validated"])
    by_category: dict[str, Any] = {}
    for category in dict.fromkeys(row["category"] for row in rows):
        group = [row for row in rows if row["category"] == category]
        group_latency = [row["latency_ms"] for row in group]
        by_category[category] = {
            "questions": len(group),
            "validated": sum(row["validated"] for row in group),
            "meets_expectation": sum(row["meets_expectation"] for row in group),
            "p50_latency_ms": round(statistics.median(group_latency), 1),
            "p95_latency_ms": round(percentile(group_latency, 0.95), 1),
            "calls": sum(len(row["calls"]) for row in group),
        }
    return {
        **meta,
        "questions": len(rows),
        "trials": sorted({row["trial"] for row in rows}),
        "http_200": sum(row["status_code"] == 200 for row in rows),
        "non_200": sum(row["status_code"] != 200 for row in rows),
        "p50_latency_ms": round(statistics.median(latency), 1) if latency else None,
        "p95_latency_ms": round(percentile(latency, 0.95), 1) if latency else None,
        "mean_latency_ms": round(statistics.mean(latency), 1) if latency else None,
        "max_latency_ms": round(max(latency), 1) if latency else None,
        "provider_calls": len(calls),
        "calls_per_question": round(len(calls) / len(rows), 2) if rows else None,
        "providers": dict(
            sorted(
                collections.Counter(str(call.get("provider")) for call in calls).items(),
                key=lambda item: -item[1],
            )
        ),
        "per_upstream": per_upstream,
        "by_answer_provider": dict(sorted(by_answer_provider.items())),
        "by_review_provider": dict(sorted(by_review_provider.items())),
        "validated": sum(row["validated"] for row in rows),
        "validated_rate": round(sum(row["validated"] for row in rows) / len(rows), 3)
        if rows
        else None,
        "validated_declined": sum(row["outcome"] == "validated_declined" for row in rows),
        "meets_expectation": sum(row["meets_expectation"] for row in rows),
        "claim_backed_meets_expectation": sum(
            row["claim_backed_meets_expectation"] for row in rows
        ),
        "outcomes": dict(collections.Counter(row["outcome"] for row in rows)),
        "call_cost_usd": round(sum(row.get("cost_usd") or 0.0 for row in rows), 8),
        "mean_cost_per_question_usd": round(
            sum(row.get("cost_usd") or 0.0 for row in rows) / len(rows), 8
        )
        if rows
        else None,
        "stages": summarize_calls(calls)["stages"],
        "by_category": by_category,
    }


async def run(limit: int, trials: int, checkpoint: Path | None = None) -> tuple[dict, list[dict]]:
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
    archive = await e2e.build_archive()
    ledger_start = await ledger_total()
    rows: list[dict[str, Any]] = []
    try:
        from app.main import create_app

        app = create_app()
        async with app.router.lifespan_context(app):
            from httpx import ASGITransport, AsyncClient

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test", timeout=90.0
            ) as client:
                for trial in range(trials):
                    await clear_answer_cache()
                    for case in selected:
                        capture.clear()
                        failures = FailureCapture()
                        root = logging.getLogger()
                        root.addHandler(failures)
                        started = time.monotonic()
                        status_code = 0
                        body: dict[str, Any] = {}
                        try:
                            response = await client.post(
                                "/analysis/query",
                                json={
                                    "question": case["question"],
                                    "season": "2025-26",
                                    "turn_id": "routing-" + uuid.uuid4().hex,
                                    "expected_revision": 0,
                                },
                            )
                            status_code = response.status_code
                            body = response.json() if status_code == 200 else {}
                        finally:
                            elapsed = (time.monotonic() - started) * 1000
                            root.removeHandler(failures)
                        trace = body.get("tool_calls") or []
                        model_stages = [
                            entry
                            for entry in trace
                            if entry.get("stage") in {"orchestrate", "review", "revise"}
                        ]
                        calls = [dict(call) for call in capture.calls]
                        for call, entry in zip(calls, model_stages, strict=False):
                            stage = entry.get("stage")
                            if stage == "orchestrate":
                                stage = "plan" if entry.get("action") == "call_tools" else "answer"
                            elif stage == "revise":
                                stage = "repair"
                            call["stage"] = stage
                            call["action"] = entry.get("action")
                        answer_calls = [call for call in calls if call.get("stage") == "answer"]
                        review_calls = [call for call in calls if call.get("stage") == "review"]
                        outcome = (
                            e2e.classify(body, failures.records) if body else f"http_{status_code}"
                        )
                        record = {
                            "id": case["id"],
                            "category": case["category"],
                            "answerable": case["answerable"],
                            "question": case["question"],
                            "outcome": outcome,
                            "answer": body.get("answer") or "",
                            "llm_validated": bool(body.get("llm_validated")),
                            "degraded": bool(body.get("degraded")),
                            "warnings": body.get("warnings") or [],
                            "tool_calls": trace,
                            "data_version": body.get("data_version"),
                            "status_code": status_code,
                        }
                        try:
                            score = e2e.score(case, record, archive)
                        except Exception as exc:  # noqa: BLE001 - keep the measurement row
                            score = {
                                "meets_expectation": False,
                                "claim_backed_meets_expectation": False,
                                "failures": [f"scoring_error:{type(exc).__name__}"],
                            }
                        row_out = {
                            "trial": trial,
                            "id": case["id"],
                            "category": case["category"],
                            "answerable": case["answerable"],
                            "status_code": status_code,
                            "latency_ms": round(elapsed, 1),
                            "outcome": outcome,
                            "validated": outcome in {"validated", "validated_declined"},
                            "meets_expectation": bool(score["meets_expectation"]),
                            "claim_backed_meets_expectation": bool(
                                score["claim_backed_meets_expectation"]
                            ),
                            "score_failures": score["failures"],
                            "answer_provider": (
                                answer_calls[-1].get("provider") if answer_calls else None
                            ),
                            "review_provider": (
                                review_calls[-1].get("provider") if review_calls else None
                            ),
                            "calls": calls,
                            "provider_calls": len(calls),
                            "cost_usd": round(
                                sum(call.get("cost_usd") or 0.0 for call in calls), 8
                            ),
                            "failure_records": failures.records,
                            "answer": body.get("answer") or "",
                            "warnings": body.get("warnings") or [],
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
        "scope": "in-process ASGI app, real OpenRouter provider, restored active release, "
        "llm_primary evidence loop, sequential single client, answer cache cleared per trial",
        "provider": settings.ai_provider,
        "model": settings.ai_chat_model,
        "answer_mode": settings.analysis_answer_mode,
        "evidence_loop": settings.analyst_evidence_loop_enabled,
        "reasoning_effort": settings.ai_reasoning_effort,
        "analyst_reasoning_effort": settings.analyst_reasoning_effort,
        "routing": {
            "order": list(settings.openrouter_provider_order),
            "sort": settings.openrouter_provider_sort,
            "allow_fallbacks": settings.openrouter_provider_allow_fallbacks,
            "require_parameters": True,
        },
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
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out_dir / f"{args.label}.rows.jsonl"
    if checkpoint.exists():
        checkpoint.unlink()
    summary, rows = asyncio.run(run(args.questions, args.trials, checkpoint))
    out = args.out_dir / f"{args.label}.summary.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"summary: {out}")
    print(f"rows: {checkpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
