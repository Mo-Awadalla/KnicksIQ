"""Input-budget A/B: the honest scorer, per-question latency, ledger cost and budget events.

Runs the same 70-question sample as ``analyst_live_e2e.py --per-category 10`` through the
in-process app, scores every response with the harness's honest scorer, and records what the
harness alone does not: wall latency, the exact monthly-ledger delta per question with its
reconciliation, the failure message behind every execution failure, and every claim dropped
from the writer payload or refused by review packing.

    DB_URL=... REDIS_URL=redis://localhost:56500/15 ANALYST_INPUT_TOKENS=8000 \
      uv run --package knicksiq-api python .../final/ab_runner.py \
        --label budget-8000 --trials 2 --out-dir .../final

Instrumentation only. The application modules are patched at runtime, never edited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import os

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

TOOLS = Path(__file__).resolve().parents[4] / "tools" / "release"
sys.path.insert(0, str(TOOLS))

import analyst_live_e2e as e2e  # noqa: E402
import measure_llm_cost as cost  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import analyst_loop  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

DROPS: list[dict[str, Any]] = []
OVERFLOWS: list[dict[str, Any]] = []
_ORIGINAL_BUILD = analyst_loop.build_payload
_ORIGINAL_MODEL = analyst_loop.request_model


def _available_claims(loop: Any) -> list[Any]:
    claims = list({c.claim_id: c for r in loop.results for c in r.claims}.values())
    return claims or list(loop.tools.claims.values())


def _build(loop: Any, schema: type, **kwargs: Any) -> dict[str, Any]:
    available = _available_claims(loop)
    review = bool(kwargs.get("review", False))
    try:
        payload = _ORIGINAL_BUILD(loop, schema, **kwargs)
    except ValueError as exc:
        DROPS.append(
            {
                "kind": "refused",
                "review": review,
                "message": str(exc),
                "available": len(available),
                "sent": 0,
            }
        )
        raise
    if review:
        DROPS.append(
            {
                "kind": "review_ok",
                "review": True,
                "available": len(available),
                "sent": len(payload.get("claims") or []),
            }
        )
    else:
        sent = set(loop.sent_claims)
        dropped = [c.claim_id for c in available if c.claim_id not in sent]
        DROPS.append(
            {
                "kind": "writer",
                "review": False,
                "available": len(available),
                "sent": len(sent),
                "dropped": len(dropped),
                "dropped_ids": dropped[:20],
            }
        )
    return payload


async def _request_model(*args: Any, **kwargs: Any) -> Any:
    try:
        return await _ORIGINAL_MODEL(*args, **kwargs)
    except Exception as exc:
        message = str(exc)
        if "budget" in message.lower() and (
            "exceeds" in message.lower() or "cannot fit" in message.lower()
        ):
            OVERFLOWS.append(
                {
                    "error": type(exc).__name__,
                    "message": message,
                    "review": bool(kwargs.get("review", False)),
                }
            )
        raise


analyst_loop.build_payload = _build
analyst_loop.request_model = _request_model


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


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 1)


async def run(picked: list[dict[str, Any]], trials: int, out_dir: Path, label: str) -> None:
    archive = await e2e.build_archive()
    app = create_app()
    rows: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", timeout=90.0
        ) as client:
            for trial in range(trials):
                await clear_answer_cache()
                for ordinal, case in enumerate(picked):
                    DROPS.clear()
                    OVERFLOWS.clear()
                    failures = FailureCapture()
                    root = logging.getLogger()
                    root.addHandler(failures)
                    ledger_before = await cost._snapshot_ledger()
                    settles_before = len(cost.SETTLES)
                    started = loop.time()
                    status_code = 0
                    body: dict[str, Any] = {}
                    try:
                        response = await client.post(
                            "/analysis/query",
                            json={
                                "question": case["question"],
                                "season": "2025-26",
                                "turn_id": "ab-" + uuid.uuid4().hex,
                                "expected_revision": 0,
                            },
                        )
                        status_code = response.status_code
                        body = response.json() if status_code == 200 else {}
                    finally:
                        elapsed_ms = (loop.time() - started) * 1000
                        root.removeHandler(failures)
                    ledger_after = await cost._snapshot_ledger()
                    settle_events = cost.SETTLES[settles_before:]
                    settled_total = sum(float(e["settled"] or 0.0) for e in settle_events)
                    ledger_delta = ledger_after["ledger"] - ledger_before["ledger"]
                    open_delta = ledger_after["open"] - ledger_before["open"]
                    outcome = (
                        e2e.classify(body, failures.records) if body else f"http_{status_code}"
                    )
                    record = {
                        "id": case["id"],
                        "category": case["category"],
                        "answerable": case["answerable"],
                        "question": case["question"],
                        "outcome": outcome,
                        "llm_validated": body.get("llm_validated", False),
                        "answer": body.get("answer") or "",
                        "citations": body.get("citations") or [],
                        "warnings": body.get("warnings") or [],
                        "refused": body.get("refused", False),
                        "degraded": body.get("degraded", False),
                        "route": body.get("route"),
                        "tool_calls": body.get("tool_calls") or [],
                        "data_version": body.get("data_version"),
                        "status_code": status_code,
                    }
                    try:
                        score = e2e.score(case, record, archive)
                    except Exception as exc:  # noqa: BLE001 - keep the measurement row
                        score = {
                            "id": case["id"],
                            "category": case["category"],
                            "answerable": case["answerable"],
                            "meets_expectation": False,
                            "old_meets_expectation": False,
                            "claim_backed_meets_expectation": False,
                            "failures": [f"scoring_error:{type(exc).__name__}"],
                        }
                    rows.append(
                        {
                            "trial": trial,
                            "ordinal": ordinal,
                            "latency_ms": round(elapsed_ms, 1),
                            "ledger_before": round(ledger_before["ledger"], 9),
                            "ledger_after": round(ledger_after["ledger"], 9),
                            "ledger_delta": round(ledger_delta, 9),
                            "open_before": round(ledger_before["open"], 9),
                            "open_after": round(ledger_after["open"], 9),
                            "settled_total": round(settled_total, 9),
                            "reconciled": round(settled_total + open_delta, 9),
                            "reconciles": abs(ledger_delta - (settled_total + open_delta)) < 1e-9,
                            "provider_calls": sum(
                                1
                                for entry in record["tool_calls"]
                                if str(entry.get("tool", "")).startswith("llm_")
                            ),
                            "input_bytes": [
                                entry.get("input_bytes")
                                for entry in record["tool_calls"]
                                if str(entry.get("tool", "")).startswith("llm_")
                            ],
                            "prompt_tokens": [
                                entry.get("prompt_tokens")
                                for entry in record["tool_calls"]
                                if str(entry.get("tool", "")).startswith("llm_")
                            ],
                            "failures": list(failures.records),
                            "overflows": list(OVERFLOWS),
                            "drops": list(DROPS),
                            **record,
                            "score": score,
                        }
                    )
                    print(
                        f"{label} trial={trial} {ordinal + 1}/{len(picked)} {case['id']} "
                        f"{outcome} {elapsed_ms:.0f}ms ${ledger_delta:.6f}",
                        flush=True,
                    )

    latency = [row["latency_ms"] for row in rows]
    by_trial: dict[str, Any] = {}
    for trial in range(trials):
        subset = [row for row in rows if row["trial"] == trial]
        by_trial[str(trial)] = {
            "questions": len(subset),
            "meets_expectation": sum(int(r["score"]["meets_expectation"]) for r in subset),
            "claim_backed": sum(
                int(r["score"]["claim_backed_meets_expectation"]) for r in subset
            ),
            "validated": sum(int(r["llm_validated"]) for r in subset),
            "p50_latency_ms": _percentile([r["latency_ms"] for r in subset], 0.5),
            "p95_latency_ms": _percentile([r["latency_ms"] for r in subset], 0.95),
            "cost_usd": round(sum(r["ledger_delta"] for r in subset), 9),
        }

    outcomes: dict[str, int] = {}
    for row in rows:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    fallback_reasons: dict[str, int] = {}
    for row in rows:
        if row["outcome"].startswith(("fallback", "failed", "http_")):
            fallback_reasons[row["outcome"]] = fallback_reasons.get(row["outcome"], 0) + 1

    writer_drops = [
        entry
        for row in rows
        for entry in row["drops"]
        if entry["kind"] == "writer" and entry.get("dropped")
    ]
    refused = [entry for row in rows for entry in row["drops"] if entry["kind"] == "refused"]
    overflows = [entry for row in rows for entry in row["overflows"]]
    summary = {
        "label": label,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_tokens": os.environ.get("ANALYST_INPUT_TOKENS"),
        "redis_db": os.environ.get("REDIS_URL", "").rsplit("/", 1)[-1],
        "questions": len(rows),
        "trials": trials,
        "by_trial": by_trial,
        "meets_expectation": sum(int(r["score"]["meets_expectation"]) for r in rows),
        "claim_backed": sum(
            int(r["score"]["claim_backed_meets_expectation"]) for r in rows
        ),
        "validated": sum(int(r["llm_validated"]) for r in rows),
        "old_meets_expectation": sum(
            int(r["score"]["old_meets_expectation"]) for r in rows
        ),
        "by_category": {
            category: {
                "questions": len([r for r in rows if r["category"] == category]),
                "meets_expectation": sum(
                    int(r["score"]["meets_expectation"])
                    for r in rows
                    if r["category"] == category
                ),
                "validated": sum(
                    int(r["llm_validated"]) for r in rows if r["category"] == category
                ),
            }
            for category in sorted({r["category"] for r in rows})
        },
        "outcomes": outcomes,
        "fallback_reasons": fallback_reasons,
        "p50_latency_ms": _percentile(latency, 0.5),
        "p95_latency_ms": _percentile(latency, 0.95),
        "mean_latency_ms": round(statistics.mean(latency), 1) if latency else 0.0,
        "ledger_delta_total": round(sum(r["ledger_delta"] for r in rows), 9),
        "settled_total": round(sum(r["settled_total"] for r in rows), 9),
        "open_delta_total": round(sum(r["open_after"] - r["open_before"] for r in rows), 9),
        "mean_cost_per_question": round(
            sum(r["ledger_delta"] for r in rows) / len(rows), 9
        )
        if rows
        else 0.0,
        "reconciles": all(r["reconciles"] for r in rows),
        "unreconciled": [r["id"] for r in rows if not r["reconciles"]],
        "budget_events": {
            "exceeds_input_budget": len(overflows),
            "exceeds_messages": sorted({entry["message"] for entry in overflows}),
            "writer_claim_drop_events": len(writer_drops),
            "writer_claims_dropped": sum(entry["dropped"] for entry in writer_drops),
            "questions_with_claim_drops": len(
                {(row["trial"], row["id"]) for row in rows for entry in row["drops"]
                 if entry["kind"] == "writer" and entry.get("dropped")}
            ),
            "max_claims_dropped_one_call": max(
                (entry["dropped"] for entry in writer_drops), default=0
            ),
            "review_packing_refusals": len(refused),
            "review_refusal_messages": sorted({entry["message"] for entry in refused}),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / f"{label}.rows.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows)
    )
    for trial in range(trials):
        subset = [row for row in rows if row["trial"] == trial]
        (out_dir / f"{label}.trial{trial + 1}.responses.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        key: row[key]
                        for key in (
                            "id",
                            "category",
                            "answerable",
                            "question",
                            "outcome",
                            "answer",
                            "citations",
                            "warnings",
                            "llm_validated",
                        )
                    }
                )
                + "\n"
                for row in subset
            )
        )
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="smoke only: cap live questions")
    args = parser.parse_args()
    cases = e2e.load_cases(e2e.QUESTIONS)
    picked = e2e.sample(cases, args.per_category, False)
    if args.limit:
        picked = picked[: args.limit]
    asyncio.run(run(picked, args.trials, args.out_dir, args.label))


if __name__ == "__main__":
    main()
