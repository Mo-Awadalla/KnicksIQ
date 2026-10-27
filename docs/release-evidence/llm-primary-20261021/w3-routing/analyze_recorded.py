"""Per-upstream table from already-recorded dev-set responses (no provider calls).

Reads the committed 8,000/16,000 final traces and the latency/cost artifacts. Provider
attribution comes from each provider response's `provider` field, recorded in the response
trace. Held-out artifacts are not read.

    uv run python docs/release-evidence/llm-primary-20261021/w3-routing/analyze_recorded.py \
        --out docs/release-evidence/llm-primary-20261021/w3-routing/recorded-upstream.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
RUNS = {
    "final-16000": BASE / "final/budget-16000.rows.jsonl",
    "final-8000": BASE / "final/budget-8000.rows.jsonl",
    "final-8000-drops": BASE / "final/budget-8000-drops.rows.jsonl",
    "latency-after-gate": BASE / "latency/after-gate.rows.jsonl",
    "latency-base-gate": BASE / "latency/base-gate.rows.jsonl",
    "latency-after-premerge": BASE / "latency/after-premerge-40.rows.jsonl",
}
COST = BASE / "cost/prod-none/calls.jsonl"


def pct(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def model_calls(row: dict[str, Any]) -> list[dict[str, Any]]:
    # Latency artifacts keep the wrapper capture in `calls`; final artifacts keep the
    # application trace in `tool_calls`. Both carry the response `provider`.
    calls = [dict(call) for call in (row.get("calls") or [])]
    if calls:
        return calls
    return [
        dict(entry)
        for entry in (row.get("tool_calls") or [])
        if entry.get("stage") in {"orchestrate", "review", "revise"}
    ]


def stage_of(call: dict[str, Any]) -> str:
    stage = call.get("stage")
    if stage == "orchestrate":
        return "plan" if call.get("action") == "call_tools" else "answer"
    if stage == "revise":
        return "repair"
    return stage or "unknown"


def load_runs() -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for run, path in RUNS.items():
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        counts[run] = len(rows)
        for row in rows:
            calls = model_calls(row)
            if not calls:
                continue
            for call in calls:
                call["stage"] = stage_of(call)
            answer = [call for call in calls if call["stage"] == "answer"]
            review = [call for call in calls if call["stage"] == "review"]
            records.append(
                {
                    "run": run,
                    "id": row.get("id"),
                    "trial": row.get("trial"),
                    "validated": bool(
                        row.get("llm_validated")
                        or row.get("validator")
                        or str(row.get("outcome", "")).startswith("validated")
                    ),
                    "answer_provider": answer[-1].get("provider") if answer else None,
                    "review_provider": review[-1].get("provider") if review else None,
                    "calls": calls,
                }
            )
    return records, counts


def summarize(records: list[dict[str, Any]], counts: dict[str, int]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    answer_validated: dict[str, list[int]] = collections.defaultdict(list)
    review_validated: dict[str, list[int]] = collections.defaultdict(list)
    for record in records:
        for call in record["calls"]:
            groups[str(call.get("provider"))].append(call)
        if record["answer_provider"]:
            answer_validated[str(record["answer_provider"])].append(int(record["validated"]))
        if record["review_provider"]:
            review_validated[str(record["review_provider"])].append(int(record["validated"]))
    providers = {}
    for provider, calls in sorted(groups.items(), key=lambda item: -len(item[1])):
        latency = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
        answers = answer_validated.get(provider, [])
        reviews = review_validated.get(provider, [])
        providers[provider] = {
            "calls": len(calls),
            "stages": dict(collections.Counter(call["stage"] for call in calls)),
            "mean_latency_ms": round(statistics.mean(latency), 1) if latency else None,
            "p50_latency_ms": round(statistics.median(latency), 1) if latency else None,
            "p95_latency_ms": round(pct(latency, 0.95), 1) if latency else None,
            "max_latency_ms": round(max(latency), 1) if latency else None,
            "finish_reasons": dict(
                collections.Counter(str(call.get("finish_reason")) for call in calls)
            ),
            "content_kinds": dict(
                collections.Counter(str(call.get("content_kind")) for call in calls)
            ),
            "reasoning_token_calls": sum(1 for call in calls if call.get("reasoning_tokens")),
            "answer_questions": len(answers),
            "answer_validated_rate": round(sum(answers) / len(answers), 3) if answers else None,
            "review_questions": len(reviews),
            "review_validated_rate": round(sum(reviews) / len(reviews), 3) if reviews else None,
        }
    per_stage: dict[str, dict[str, Any]] = {}
    for stage in ("plan", "answer", "review", "repair"):
        table = {}
        for provider in groups:
            calls = [call for call in groups[provider] if call["stage"] == stage]
            latency = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
            if calls:
                table[provider] = {
                    "calls": len(calls),
                    "p50_ms": round(statistics.median(latency), 1) if latency else None,
                    "p95_ms": round(pct(latency, 0.95), 1) if latency else None,
                }
        per_stage[stage] = table
    costs = []
    if COST.exists():
        for line in COST.read_text().splitlines():
            if line.strip():
                costs.append(json.loads(line))
    cost_by_provider: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for call in costs:
        grouped[str(call.get("upstream_provider"))].append(call)
    for provider, calls in sorted(grouped.items(), key=lambda item: -len(item[1])):
        prompt = sum(call.get("prompt_tokens") or 0 for call in calls)
        completion = sum(call.get("completion_tokens") or 0 for call in calls)
        reported = sum(call.get("usage_cost_usd") or 0.0 for call in calls)
        cost_by_provider[provider] = {
            "calls": len(calls),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "reported_cost_usd": round(reported, 8),
            "effective_prompt_usd_per_m": round(reported * 1e6 / prompt, 4) if prompt else None,
            "effective_completion_usd_per_m": (
                round(reported * 1e6 / completion, 4) if completion else None
            ),
            "finish_reasons": dict(
                collections.Counter(str(call.get("finish_reason")) for call in calls)
            ),
        }
    return {
        "runs": counts,
        "records": len(records),
        "calls": sum(len(record["calls"]) for record in records),
        "providers": providers,
        "per_stage": per_stage,
        "cost_artifact": {
            "path": str(COST.relative_to(BASE.parents[2])) if COST.exists() else None,
            "calls": len(costs),
            "by_provider": cost_by_provider,
            "note": "Single 20-question production run; effective rates include prompt/completion "
            "mix and cached tokens, not the list prices.",
        },
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "| Provider | Calls | Stages | p50 ms | p95 ms | Finish | Content | "
        "Answer questions | Answer validated | Review questions | Review validated |",
        "| --- | ---: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for provider, row in result["providers"].items():
        stages = " ".join(f"{name}:{count}" for name, count in row["stages"].items())
        lines.append(
            f"| {provider} | {row['calls']} | {stages} | {row['p50_latency_ms']} | "
            f"{row['p95_latency_ms']} | {row['finish_reasons']} | {row['content_kinds']} | "
            f"{row['answer_questions']} | {row['answer_validated_rate']} | "
            f"{row['review_questions']} | {row['review_validated_rate']} |"
        )
    lines += [
        "",
        "| Stage | Provider | Calls | p50 ms | p95 ms |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for stage, table in result["per_stage"].items():
        for provider, row in table.items():
            lines.append(
                f"| {stage} | {provider} | {row['calls']} | {row['p50_ms']} | {row['p95_ms']} |"
            )
    lines += [
        "",
        "| Cost provider | Calls | Prompt tokens | Completion tokens | Reported $ | "
        "Effective prompt $/M | Effective completion $/M |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for provider, row in result["cost_artifact"]["by_provider"].items():
        lines.append(
            f"| {provider} | {row['calls']} | {row['prompt_tokens']} | "
            f"{row['completion_tokens']} | {row['reported_cost_usd']} | "
            f"{row['effective_prompt_usd_per_m']} | {row['effective_completion_usd_per_m']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records, counts = load_runs()
    result = summarize(records, counts)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(markdown(result))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
