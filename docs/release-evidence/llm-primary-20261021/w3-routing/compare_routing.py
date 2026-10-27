"""Render the routing before/after and per-upstream tables from two rows artifacts.

    uv run python docs/release-evidence/llm-primary-20261021/w3-routing/compare_routing.py \
        --before before.rows.jsonl --after after.rows.jsonl --out comparison.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from pathlib import Path
from typing import Any


def pct(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency = [row["latency_ms"] for row in rows]
    calls = [call for row in rows for call in row["calls"]]
    cost = [call["cost_usd"] for call in calls if call.get("cost_usd") is not None]
    return {
        "questions": len(rows),
        "p50_latency_ms": round(statistics.median(latency), 1),
        "p95_latency_ms": round(pct(latency, 0.95), 1),
        "mean_latency_ms": round(statistics.mean(latency), 1),
        "max_latency_ms": round(max(latency), 1),
        "validated": sum(row["validated"] for row in rows),
        "validated_declined": sum(row["outcome"] == "validated_declined" for row in rows),
        "meets_expectation": sum(row["meets_expectation"] for row in rows),
        "provider_calls": len(calls),
        "calls_per_question": round(len(calls) / len(rows), 2),
        "providers": dict(
            collections.Counter(str(call.get("provider")) for call in calls).most_common()
        ),
        "call_cost_usd": round(sum(cost), 8),
        "mean_cost_per_question_usd": round(sum(cost) / len(rows), 8),
        "finish_reasons": dict(
            collections.Counter(str(call.get("finish_reason")) for call in calls)
        ),
    }


def upstream(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        for call in row["calls"]:
            groups[str(call.get("provider"))].append(call)
    answer_validated: dict[str, list[int]] = collections.defaultdict(list)
    review_validated: dict[str, list[int]] = collections.defaultdict(list)
    for row in rows:
        if row.get("answer_provider"):
            answer_validated[str(row["answer_provider"])].append(int(row["validated"]))
        if row.get("review_provider"):
            review_validated[str(row["review_provider"])].append(int(row["validated"]))
    table = {}
    for provider, calls in sorted(groups.items(), key=lambda item: -len(item[1])):
        latency = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
        cost = [call["cost_usd"] for call in calls if call.get("cost_usd") is not None]
        answers = answer_validated.get(provider, [])
        reviews = review_validated.get(provider, [])
        table[provider] = {
            "calls": len(calls),
            "stages": dict(collections.Counter(call.get("stage") or "?" for call in calls)),
            "mean_latency_ms": round(statistics.mean(latency), 1),
            "p50_latency_ms": round(statistics.median(latency), 1),
            "p95_latency_ms": round(pct(latency, 0.95), 1),
            "mean_cost_usd": round(statistics.mean(cost), 8),
            "total_cost_usd": round(sum(cost), 8),
            "finish_reasons": dict(
                collections.Counter(str(call.get("finish_reason")) for call in calls)
            ),
            "json_ok_rate": round(sum(1 for call in calls if call.get("json_ok")) / len(calls), 3),
            "failed_calls": sum(1 for call in calls if call.get("status") != "ok"),
            "answer_questions": len(answers),
            "answer_validated_rate": round(sum(answers) / len(answers), 3) if answers else None,
            "review_questions": len(reviews),
            "review_validated_rate": round(sum(reviews) / len(reviews), 3) if reviews else None,
        }
    return table


def paired(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    left = {(row["trial"], row["id"]): row for row in before}
    right = {(row["trial"], row["id"]): row for row in after}
    keys = sorted(set(left) & set(right))
    delta = [right[key]["latency_ms"] - left[key]["latency_ms"] for key in keys]
    return {
        "paired_rows": len(keys),
        "before_p50_ms": round(statistics.median([left[key]["latency_ms"] for key in keys]), 1),
        "after_p50_ms": round(statistics.median([right[key]["latency_ms"] for key in keys]), 1),
        "before_p95_ms": round(pct([left[key]["latency_ms"] for key in keys], 0.95), 1),
        "after_p95_ms": round(pct([right[key]["latency_ms"] for key in keys], 0.95), 1),
        "mean_delta_ms": round(statistics.mean(delta), 1),
        "before_validated": sum(left[key]["validated"] for key in keys),
        "after_validated": sum(right[key]["validated"] for key in keys),
    }


def markdown(result: dict[str, Any]) -> str:
    lines = ["## Arms", "", "| Metric | Before | After |", "| --- | ---: | ---: |"]
    for key in (
        "questions",
        "p50_latency_ms",
        "p95_latency_ms",
        "mean_latency_ms",
        "max_latency_ms",
        "provider_calls",
        "calls_per_question",
        "validated",
        "validated_declined",
        "meets_expectation",
        "call_cost_usd",
        "mean_cost_per_question_usd",
    ):
        lines.append(f"| {key} | {result['before'][key]} | {result['after'][key]} |")
    lines += ["", "## Per upstream, before", ""]
    lines += [
        "| Provider | Calls | Stages | p50 ms | p95 ms | Mean cost $ | JSON ok | Finish | "
        "Answer questions | Answer validated | Review questions | Review validated |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for provider, row in result["per_upstream_before"].items():
        stages = " ".join(f"{name}:{count}" for name, count in row["stages"].items())
        finish = " ".join(f"{name}:{count}" for name, count in row["finish_reasons"].items())
        lines.append(
            f"| {provider} | {row['calls']} | {stages} | {row['p50_latency_ms']} | "
            f"{row['p95_latency_ms']} | {row['mean_cost_usd']} | {row['json_ok_rate']} | "
            f"{finish} | {row['answer_questions']} | {row['answer_validated_rate']} | "
            f"{row['review_questions']} | {row['review_validated_rate']} |"
        )
    lines += ["", "## Per upstream, after", ""]
    lines += [
        "| Provider | Calls | Stages | p50 ms | p95 ms | Mean cost $ | JSON ok | Finish | "
        "Answer questions | Answer validated | Review questions | Review validated |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for provider, row in result["per_upstream_after"].items():
        stages = " ".join(f"{name}:{count}" for name, count in row["stages"].items())
        finish = " ".join(f"{name}:{count}" for name, count in row["finish_reasons"].items())
        lines.append(
            f"| {provider} | {row['calls']} | {stages} | {row['p50_latency_ms']} | "
            f"{row['p95_latency_ms']} | {row['mean_cost_usd']} | {row['json_ok_rate']} | "
            f"{finish} | {row['answer_questions']} | {row['answer_validated_rate']} | "
            f"{row['review_questions']} | {row['review_validated_rate']} |"
        )
    lines += ["", "## Paired", "", "| Metric | Value |", "| --- | ---: |"]
    for key, value in result["paired"].items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before, after = load(args.before), load(args.after)
    result = {
        "before": arm(before),
        "after": arm(after),
        "per_upstream_before": upstream(before),
        "per_upstream_after": upstream(after),
        "paired": paired(before, after),
    }
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
