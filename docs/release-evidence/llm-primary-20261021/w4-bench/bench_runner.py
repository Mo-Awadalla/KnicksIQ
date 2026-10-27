"""The 70-question live benchmark with the honest scorer, priced ledger and stage latency.

Writes the ``analyst_live_e2e.py --per-category 10`` artifacts plus the ledger delta per
question, every priced provider call and the per-stage latency table.

    . /tmp/go.env && export REDIS_URL=redis://localhost:56500/2
    uv run --package knicksiq-api python .../bench_runner.py --trials 2 --out-dir ...

Instrumentation only; no application file is edited.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import statistics
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

TOOLS = Path(__file__).resolve().parents[4] / "tools" / "release"
sys.path.insert(0, str(TOOLS))

import analyst_live_e2e as e2e  # noqa: E402
import app.services.report_llm as report_llm  # noqa: E402
import measure_llm_cost as cost  # noqa: E402
from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from latency_stats import bucket  # noqa: E402

# The Go host reports no per-call cost; report_llm prices it after parsing. Record that value,
# because measure_llm_cost reads only the raw HTTP body where usage.cost is absent.
_PROVIDER_GENERATE = report_llm.OpenAICompatibleLLMAdapter.generate


async def _priced_generate(self: Any, *, system: str, user: str) -> str:
    try:
        return await _PROVIDER_GENERATE(self, system=system, user=user)
    finally:
        if cost.CALLS and cost.CALLS[-1].get("assembly_returned"):
            usage = (getattr(self, "last_metadata", {}) or {}).get("usage") or {}
            cost.CALLS[-1]["priced_cost_usd"] = usage.get("cost")


report_llm.OpenAICompatibleLLMAdapter.generate = _priced_generate

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
                    "message": record.getMessage()[:800],
                }
            )


def percentile(values: list[float], fraction: float, digits: int = 1) -> float | None:
    """Nearest-rank percentile, the method in tools/release/latency_stats.py."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], digits)


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


def stage_entries(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trace entries with their own elapsed time; prepare_total is a total, not a stage."""
    return [entry for entry in trace if entry.get("tool") != "prepare_total"]


async def run(picked: list[dict[str, Any]], trials: int) -> dict[str, Any]:
    from app.core.config import get_settings

    reservation_usd = get_settings().analyst_call_reservation_usd
    archive = await e2e.build_archive()
    app = create_app()
    loop = asyncio.get_running_loop()
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=90.0) as client:
            for trial in range(trials):
                await clear_answer_cache()
                for ordinal, case in enumerate(picked):
                    failures = FailureCapture()
                    root = logging.getLogger()
                    root.addHandler(failures)
                    calls_before = len(cost.CALLS)
                    settles_before = len(cost.SETTLES)
                    ledger_before = await cost._snapshot_ledger()
                    started = loop.time()
                    status_code = 0
                    body: dict[str, Any] = {}
                    try:
                        response = await client.post(
                            "/analysis/query",
                            json={
                                "question": case["question"],
                                "season": "2025-26",
                                "turn_id": "bench-" + uuid.uuid4().hex,
                                "expected_revision": 0,
                            },
                        )
                        status_code = response.status_code
                        body = response.json() if status_code == 200 else {}
                    finally:
                        elapsed_ms = round((loop.time() - started) * 1000, 1)
                        root.removeHandler(failures)
                    ledger_after = await cost._snapshot_ledger()
                    settle_events = cost.SETTLES[settles_before:]
                    settled_total = sum(float(e["settled"] or 0.0) for e in settle_events)
                    ledger_delta = ledger_after["ledger"] - ledger_before["ledger"]
                    open_delta = ledger_after["open"] - ledger_before["open"]
                    outcome = (
                        e2e.classify(body, failures.records) if body else f"http_{status_code}"
                    )
                    trace = body.get("tool_calls") or []
                    provider_trace = [
                        entry for entry in trace if str(entry.get("tool", "")).startswith("llm_")
                    ]
                    turn_calls = cost.CALLS[calls_before:]
                    charged = 0.0
                    for index, call in enumerate(turn_calls):
                        entry = provider_trace[index] if index < len(provider_trace) else {}
                        reported = call.get("priced_cost_usd")
                        if reported is None:
                            reported = call.get("usage_cost_usd")
                        charge = float(reported) if reported is not None else float(reservation_usd)
                        charged += charge
                        calls.append(
                            {
                                "trial": trial,
                                "id": case["id"],
                                "stage": entry.get("stage"),
                                "tool": entry.get("tool"),
                                "model": entry.get("model"),
                                "served_model": entry.get("served_model"),
                                "protocol": entry.get("protocol"),
                                "latency_ms": entry.get("latency_ms"),
                                "prompt_tokens": call.get("prompt_tokens"),
                                "completion_tokens": call.get("completion_tokens"),
                                "reasoning_tokens": call.get("reasoning_tokens"),
                                "finish_reason": call.get("finish_reason"),
                                "error": call.get("error"),
                                "reported_cost_usd": reported,
                                "charged_usd": round(charge, 10),
                            }
                        )
                    record = {
                        "id": case["id"],
                        "category": case["category"],
                        "answerable": case["answerable"],
                        "question": case["question"],
                        "outcome": outcome,
                        "old_meets_expectation": e2e.old_meets_expectation(case, outcome),
                        "answer": body.get("answer") or "",
                        "citations": body.get("citations") or [],
                        "warnings": body.get("warnings") or [],
                        "refused": body.get("refused", False),
                        "degraded": body.get("degraded", False),
                        "llm_validated": body.get("llm_validated", False),
                        "route": body.get("route"),
                        "tool_calls": trace,
                        "status_code": status_code,
                    }
                    score = e2e.score(case, record, archive)
                    stages: dict[str, float] = dict.fromkeys(STAGE_ORDER, 0.0)
                    for entry in stage_entries(trace):
                        stages[bucket(entry)] += float(entry.get("latency_ms") or 0)
                    ledger_row = {
                        "trial": trial,
                        "id": case["id"],
                        "category": case["category"],
                        "answerable": case["answerable"],
                        "outcome": outcome,
                        "latency_ms": elapsed_ms,
                        "provider_calls": len(turn_calls),
                        "stages_ms": {key: round(value, 1) for key, value in stages.items()},
                        "ledger_before": round(ledger_before["ledger"], 9),
                        "ledger_after": round(ledger_after["ledger"], 9),
                        "ledger_delta": round(ledger_delta, 10),
                        "open_before": round(ledger_before["open"], 9),
                        "open_after": round(ledger_after["open"], 9),
                        "open_delta": round(open_delta, 10),
                        "settled_total": round(settled_total, 10),
                        "per_call_charged": round(charged, 10),
                        "reconciled": round(charged + open_delta, 10),
                        "reconciles": abs(ledger_delta - (charged + open_delta)) < 1e-9,
                        "failures": list(failures.records),
                    }
                    ledger_rows.append(ledger_row)
                    rows.append(
                        {
                            **record,
                            "trial": trial,
                            "ordinal": ordinal,
                            "latency_ms": elapsed_ms,
                            "stages_ms": ledger_row["stages_ms"],
                            "provider_calls": len(turn_calls),
                            "ledger_delta": ledger_row["ledger_delta"],
                            "per_call_charged": ledger_row["per_call_charged"],
                            "reconciles": ledger_row["reconciles"],
                            "score": score,
                        }
                    )
                    print(
                        f"trial={trial} {ordinal + 1}/{len(picked)} {case['id']} {outcome} "
                        f"{elapsed_ms:.0f}ms calls={len(turn_calls)} "
                        f"${ledger_delta:.6f} ok={ledger_row['reconciles']}",
                        flush=True,
                    )
    return {"rows": rows, "calls": calls, "ledger": ledger_rows}


def summarize(
    rows: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    trials: int,
) -> dict[str, Any]:
    by_trial: dict[str, Any] = {}
    by_category: dict[str, dict[str, list[int]]] = {}
    for trial in range(trials):
        subset = [row for row in rows if row["trial"] == trial]
        by_trial[str(trial + 1)] = {
            "questions": len(subset),
            "meets_expectation": sum(int(r["score"]["meets_expectation"]) for r in subset),
            "claim_backed": sum(int(r["score"]["claim_backed_meets_expectation"]) for r in subset),
            "validated": sum(int(r["llm_validated"]) for r in subset),
            "p50_latency_ms": percentile([r["latency_ms"] for r in subset], 0.5),
            "p95_latency_ms": percentile([r["latency_ms"] for r in subset], 0.95),
            "mean_latency_ms": round(statistics.mean([r["latency_ms"] for r in subset]), 1),
            "ledger_delta_usd": round(sum(r["ledger_delta"] for r in subset), 9),
            "mean_cost_per_question_usd": round(
                sum(r["ledger_delta"] for r in subset) / len(subset), 9
            ),
            "provider_calls": sum(r["provider_calls"] for r in subset),
            "mean_calls_per_question": round(
                sum(r["provider_calls"] for r in subset) / len(subset), 2
            ),
            "unsupported_declined": sum(
                1 for r in subset if not r["answerable"] and r["outcome"] == "validated_declined"
            ),
            "unsupported_questions": sum(1 for r in subset if not r["answerable"]),
            "reconciles": all(r["reconciles"] for r in subset),
        }
        for category in sorted({r["category"] for r in subset}):
            bucket_row = by_category.setdefault(category, {"trial1": [], "trial2": []})
            bucket_row[f"trial{trial + 1}"] = [
                int(r["score"]["meets_expectation"]) for r in subset if r["category"] == category
            ]

    stage_values: dict[str, list[float]] = {name: [] for name in STAGE_ORDER}
    stage_totals: dict[str, float] = dict.fromkeys(STAGE_ORDER, 0.0)
    for row in rows:
        for entry in stage_entries(row["tool_calls"]):
            name = bucket(entry)
            value = float(entry.get("latency_ms") or 0)
            stage_values[name].append(value)
            stage_totals[name] += value
    total_stage_ms = sum(stage_totals.values()) or 1.0
    stage_table = {
        name: {
            "calls": len(stage_values[name]),
            "p50_ms": percentile(stage_values[name], 0.5),
            "p95_ms": percentile(stage_values[name], 0.95),
            "mean_ms": round(statistics.mean(stage_values[name]), 1)
            if stage_values[name]
            else None,
            "share_of_stage_total": round(stage_totals[name] / total_stage_ms, 3),
        }
        for name in STAGE_ORDER
    }
    by_category_scores = {
        category: {
            "trial1": f"{sum(values['trial1'])}/{len(values['trial1'])}",
            "trial2": f"{sum(values['trial2'])}/{len(values['trial2'])}",
        }
        for category, values in by_category.items()
    }
    total_ledger = sum(r["ledger_delta"] for r in rows)
    total_charged = sum(c["charged_usd"] for c in calls)
    total_settled = sum(r["settled_total"] for r in ledger)
    total_open_delta = sum(r["open_delta"] for r in ledger)
    mean_cost = total_ledger / len(rows)
    call_counts = [r["provider_calls"] for r in rows]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "redis_db": os.environ.get("REDIS_URL", "").rsplit("/", 1)[-1],
        "questions": len(rows),
        "trials": trials,
        "by_trial": by_trial,
        "spread_meets_expectation": max(v["meets_expectation"] for v in by_trial.values())
        - min(v["meets_expectation"] for v in by_trial.values()),
        "by_category": by_category_scores,
        "latency": {
            "p50_ms": percentile([r["latency_ms"] for r in rows], 0.5),
            "p95_ms": percentile([r["latency_ms"] for r in rows], 0.95),
            "mean_ms": round(statistics.mean([r["latency_ms"] for r in rows]), 1),
            "by_stage": stage_table,
        },
        "calls": {
            "total": len(calls),
            "mean_per_question": round(statistics.mean(call_counts), 2),
            "p50_per_question": percentile([float(v) for v in call_counts], 0.5),
            "p95_per_question": percentile([float(v) for v in call_counts], 0.95),
            "max_per_question": max(call_counts),
            "by_stage": {
                name: sum(1 for c in calls if c.get("stage") == name)
                for name in ("orchestrate", "review", "revise")
            },
            "by_model": {
                model: sum(1 for c in calls if c.get("model") == model)
                for model in sorted({str(c.get("model")) for c in calls})
            },
            "by_protocol": {
                protocol: sum(1 for c in calls if c.get("protocol") == protocol)
                for protocol in sorted({str(c.get("protocol")) for c in calls})
            },
            "errors": sum(1 for c in calls if c.get("error")),
        },
        "cost": {
            "ledger_delta_total_usd": round(total_ledger, 9),
            "per_call_charged_total_usd": round(total_charged, 9),
            "settled_total_usd": round(total_settled, 9),
            "open_delta_total_usd": round(total_open_delta, 9),
            "reconciled_total_usd": round(total_charged + total_open_delta, 9),
            "reconciles": abs(total_ledger - (total_charged + total_open_delta)) < 1e-9,
            "unreconciled_questions": [r["id"] for r in ledger if not r["reconciles"]],
            "mean_per_question_usd": round(mean_cost, 9),
            "p50_per_question_usd": percentile([r["ledger_delta"] for r in rows], 0.5, 9),
            "p95_per_question_usd": percentile([r["ledger_delta"] for r in rows], 0.95, 9),
            "monthly_capacity_at_2_usd": int(2.0 / mean_cost) if mean_cost else None,
        },
        "outcomes": {
            outcome: sum(1 for r in rows if r["outcome"] == outcome)
            for outcome in sorted({r["outcome"] for r in rows})
        },
    }


def write_artifacts(
    out_dir: Path,
    rows: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    trials: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for trial in range(trials):
        subset = [row for row in rows if row["trial"] == trial]
        summary = e2e.summarize("live", str(e2e.QUESTIONS), subset)
        (out_dir / f"trial{trial + 1}.json").write_text(json.dumps(summary, indent=2) + "\n")
        (out_dir / f"trial{trial + 1}.scored.jsonl").write_text(
            "".join(json.dumps(item["score"]) + "\n" for item in subset)
        )
        (out_dir / f"trial{trial + 1}.responses.jsonl").write_text(
            "".join(
                json.dumps({key: value for key, value in item.items() if key != "score"}) + "\n"
                for item in subset
            )
        )
    (out_dir / "calls.jsonl").write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in calls)
    )
    (out_dir / "ledger.jsonl").write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in ledger)
    )
    (out_dir / "metrics.json").write_text(
        json.dumps(summarize(rows, calls, ledger, trials), indent=2) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--per-category", type=int, default=10)
    args = parser.parse_args()
    cases = e2e.load_cases(e2e.QUESTIONS)
    picked = e2e.sample(cases, args.per_category, False)
    measured = asyncio.run(run(picked, args.trials))
    write_artifacts(
        args.out_dir, measured["rows"], measured["calls"], measured["ledger"], args.trials
    )
    print(
        json.dumps(
            summarize(measured["rows"], measured["calls"], measured["ledger"], args.trials),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
