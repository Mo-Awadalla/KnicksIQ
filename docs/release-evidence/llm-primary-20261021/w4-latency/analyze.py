"""Build the w4-latency evidence summary from the committed artifacts (no live calls)."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STAGES = ("plan", "answer", "review", "repair")


def pct(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 1)


def stage_of(entry: dict[str, Any]) -> str:
    stage = entry.get("stage")
    if stage == "orchestrate":
        return "plan" if entry.get("action") == "call_tools" else "answer"
    if stage == "revise":
        return "repair"
    return stage or "other"


def load_run(name: str) -> dict[str, Any]:
    root = HERE / name
    metrics = json.loads((root / "metrics.json").read_text())
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines() if line]
    traces = []
    for trial in (1, 2):
        for line in (root / f"trial{trial}.responses.jsonl").read_text().splitlines():
            if line:
                traces.append(json.loads(line))
    # Every LLM trace entry corresponds to one calls.jsonl row, in order.
    entries = [
        entry
        for row in traces
        for entry in row["tool_calls"]
        if str(entry.get("tool", "")).startswith("llm_")
    ]
    for entry, call in zip(entries, calls):
        if call.get("started_utc"):
            entry["started_utc"] = call["started_utc"]
    return {"metrics": metrics, "calls": calls, "traces": traces}


def stage_table(run: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in run["traces"]:
        for entry in row["tool_calls"]:
            if str(entry.get("tool", "")).startswith("llm_"):
                groups[stage_of(entry)].append(entry)
    totals = {name: sum(e["latency_ms"] for e in groups[name]) for name in groups}
    grand = sum(totals.values()) or 1
    table = {}
    for name in STAGES:
        rows = groups.get(name, [])
        if not rows:
            table[name] = {"calls": 0}
            continue
        completion = [e.get("completion_tokens") or 0 for e in rows]
        table[name] = {
            "calls": len(rows),
            "p50_ms": pct([e["latency_ms"] for e in rows], 0.5),
            "p95_ms": pct([e["latency_ms"] for e in rows], 0.95),
            "mean_ms": round(statistics.mean(e["latency_ms"] for e in rows), 1),
            "share": round(totals[name] / grand, 3),
            "completion_p50": pct(completion, 0.5),
            "ms_per_output_token": round(
                statistics.median(
                    e["latency_ms"] / c for e, c in zip(rows, completion) if c
                ),
                2,
            )
            if any(completion)
            else None,
        }
    return table


def regress(rows: list[dict[str, Any]]) -> dict[str, float]:
    X = [[1, r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0] for r in rows]
    y = [r["latency_ms"] for r in rows]
    n = len(X)
    A = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(3)] for i in range(3)]
    b = [sum(X[k][i] * y[k] for k in range(n)) for i in range(3)]
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(3):
        pivot = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[pivot] = M[pivot], M[i]
        for r in range(3):
            if r != i:
                factor = M[r][i] / M[i][i]
                for c in range(i, 4):
                    M[r][c] -= factor * M[i][c]
    coef = [M[i][3] / M[i][i] for i in range(3)]
    ss = sum((y[k] - sum(coef[i] * X[k][i] for i in range(3))) ** 2 for k in range(n))
    sst = sum((v - statistics.mean(y)) ** 2 for v in y)
    return {
        "intercept_ms": round(coef[0]),
        "ms_per_prompt_token": round(coef[1], 3),
        "ms_per_completion_token": round(coef[2], 3),
        "r2": round(1 - ss / sst, 2),
    }


def hour_table(run: dict[str, Any]) -> dict[str, Any]:
    hours: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in run["traces"]:
        for entry in row["tool_calls"]:
            if str(entry.get("tool", "")).startswith("llm_"):
                hours[entry.get("started_utc", "")[:13] + ":00Z" if entry.get("started_utc") else "unknown"].append(entry)
    table = {}
    for hour, rows in sorted(hours.items()):
        by_stage = defaultdict(list)
        for entry in rows:
            by_stage[stage_of(entry)].append(entry["latency_ms"])
        table[hour] = {
            "calls": len(rows),
            "p50_ms": pct([e["latency_ms"] for e in rows], 0.5),
            "p95_ms": pct([e["latency_ms"] for e in rows], 0.95),
            **{name: pct(values, 0.5) for name, values in sorted(by_stage.items())},
        }
    return table


def probe_table() -> dict[str, Any]:
    rows = []
    for path in sorted(HERE.glob("probe*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["payload"], row["combo"])].append(row)
    table = {}
    for (payload, combo), items in sorted(groups.items()):
        good = [r for r in items if r["status"] == 200]
        table[f"{payload}|{combo}"] = {
            "n": len(good),
            "p50_ms": pct([r["latency_ms"] for r in good], 0.5),
            "completion_tokens": [r["completion_tokens"] for r in good],
            "request_bytes": [r["request_bytes"] for r in good],
        }
    ping = [
        json.loads(line) for line in (HERE / "ping.jsonl").read_text().splitlines() if line
    ]
    ping_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ping:
        if row["status"] == 200:
            ping_groups[f"{row['target']}|{row['combo']}"].append(row)
    return {
        "payloads": table,
        "ping": {
            key: {"n": len(items), "p50_ms": pct([r["latency_ms"] for r in items], 0.5)}
            for key, items in sorted(ping_groups.items())
        },
        "hours": sorted({row["hour_utc"] for row in rows}),
    }


def main() -> None:
    summary: dict[str, Any] = {}
    for name in ("before", "after"):
        try:
            run = load_run(name)
        except FileNotFoundError:
            continue
        m = run["metrics"]
        summary[name] = {
            "questions": m["questions"],
            "by_trial": {
                key: {
                    aspect: value[aspect]
                    for aspect in ("p50_latency_ms", "p95_latency_ms", "meets_expectation", "validated")
                }
                for key, value in m["by_trial"].items()
            },
            "overall": {
                key: m["latency"][key] for key in ("p50_ms", "p95_ms", "mean_ms")
            },
            "calls": m["calls"]["total"],
            "calls_per_question": m["calls"]["mean_per_question"],
            "outcomes": m["outcomes"],
            "stages": stage_table(run),
            "by_hour": hour_table(run),
            "regression": {
                stage: regress(
                    [
                        entry
                        for row in run["traces"]
                        for entry in row["tool_calls"]
                        if str(entry.get("tool", "")).startswith("llm_")
                        and stage_of(entry) == stage
                    ]
                )
                for stage in STAGES
            },
        }
    summary["probe"] = probe_table()
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
