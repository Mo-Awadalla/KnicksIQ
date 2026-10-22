"""Latency A/B on the same 30 questions x 2 trials, with per-call UTC timestamps.

Reuses the committed benchmark runner (sample, honest scorer, ledger reconciliation) and adds
only instrumentation: a deterministic 30-question selection across all seven categories, the
exact provider payload captured once per schema, and UTC start/end for every provider call.

    . /tmp/go.env && export REDIS_URL=redis://localhost:56500/8
    docker exec kiq-integrate-redis-1 redis-cli -n 8 flushdb
    uv run --package knicksiq-api python .../w4-latency/latency_ab.py --out-dir .../before

Instrumentation only; no application file is edited here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent
BENCH = EVIDENCE / "w4-bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(HERE.parents[3] / "tools" / "release"))

import bench_runner  # noqa: E402
import analyst_live_e2e as e2e  # noqa: E402
import app.services.report_llm as report_llm  # noqa: E402

# The runner already wrapped generate for pricing; wrap that wrapper with timestamps/capture.
_PRICED_GENERATE = report_llm.OpenAICompatibleLLMAdapter.generate
_CALLS: list[dict[str, Any]] = []
_PAYLOADS: dict[str, dict[str, Any]] = {}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def schema_title(user: str) -> str | None:
    try:
        value = json.loads(user)
    except (TypeError, ValueError):
        return None
    schema = value.get("schema") if isinstance(value, dict) else None
    return schema.get("title") if isinstance(schema, dict) else None


async def _instrumented(self: Any, *, system: str, user: str) -> str:
    title = schema_title(user)
    record: dict[str, Any] = {
        "started_utc": utc_now(),
        "schema": title,
        "model": getattr(self, "model", None),
        "max_tokens": getattr(self, "max_tokens", None),
        "input_bytes": len(system.encode()) + len(user.encode()),
        "error": None,
    }
    _CALLS.append(record)
    try:
        return await _PRICED_GENERATE(self, system=system, user=user)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        record["error"] = type(exc).__name__
        raise
    finally:
        record["ended_utc"] = utc_now()
        if title and title not in _PAYLOADS and "repair" not in user[:4000]:
            _PAYLOADS[title] = {
                "system": system,
                "user": user,
                "model": getattr(self, "model", None),
                "max_tokens": getattr(self, "max_tokens", None),
                "reasoning_effort": getattr(self, "reasoning_effort", None),
                "protocol": getattr(self, "protocols", {}).get(getattr(self, "model", ""), "chat"),
            }


report_llm.OpenAICompatibleLLMAdapter.generate = _instrumented


def pick_30(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin five/five/four/four/four/four/four from the 70-question bench sample.

    The benchmark sample is 10 per category in file order. Round-robin keeps every category
    represented in 30 questions and is a pure function of the question file.
    """
    sample = e2e.sample(cases, 10, False)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in sample:
        by_category.setdefault(row["category"], []).append(row)
    picked: list[dict[str, Any]] = []
    index = 0
    while len(picked) < 30 and index < 10:
        for category in sorted(by_category):
            if index < len(by_category[category]) and len(picked) < 30:
                picked.append(by_category[category][index])
        index += 1
    return picked


def attach_times(calls: list[dict[str, Any]]) -> None:
    for index, call in enumerate(calls):
        if index < len(_CALLS):
            call.update(
                started_utc=_CALLS[index]["started_utc"],
                ended_utc=_CALLS[index].get("ended_utc"),
                input_bytes=_CALLS[index]["input_bytes"],
            )


def by_hour(calls: list[dict[str, Any]]) -> dict[str, Any]:
    hours: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        stamp = call.get("started_utc")
        if not stamp:
            continue
        hours.setdefault(stamp[:13] + ":00Z", []).append(call)
    return {
        hour: {
            "calls": len(rows),
            "p50_ms": bench_runner.percentile([r["latency_ms"] for r in rows if r.get("latency_ms")], 0.5),
            "p95_ms": bench_runner.percentile([r["latency_ms"] for r in rows if r.get("latency_ms")], 0.95),
        }
        for hour, rows in sorted(hours.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    cases = e2e.load_cases(e2e.QUESTIONS)
    picked = pick_30(cases)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "questions.jsonl").write_text(
        "".join(json.dumps({"id": row["id"], "category": row["category"]}) + "\n" for row in picked)
    )
    measured = asyncio.run(bench_runner.run(picked, args.trials))
    attach_times(measured["calls"])
    bench_runner.write_artifacts(
        args.out_dir, measured["rows"], measured["calls"], measured["ledger"], args.trials
    )
    summary = bench_runner.summarize(
        measured["rows"], measured["calls"], measured["ledger"], args.trials
    )
    summary["by_hour_utc"] = by_hour(measured["calls"])
    summary["sample_ids"] = [row["id"] for row in picked]
    summary["sample"] = "round-robin 5/5/4/4/4/4/4 of the 10-per-category bench sample"
    (args.out_dir / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out_dir / "payloads.json").write_text(json.dumps(_PAYLOADS, indent=1) + "\n")
    (args.out_dir / "calls.jsonl").write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in measured["calls"])
    )
    print(json.dumps({k: summary[k] for k in ("by_trial", "latency", "calls", "outcomes")}, indent=2))


if __name__ == "__main__":
    main()
