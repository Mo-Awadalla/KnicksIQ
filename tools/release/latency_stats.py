"""Stage aggregation for the live latency measurement."""

from __future__ import annotations

import collections
import math
import statistics
from typing import Any

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
        "meets_expectation": sum(bool(row.get("meets_expectation")) for row in rows),
        "meets_expectation_rate": round(
            sum(bool(row.get("meets_expectation")) for row in rows) / len(rows), 3
        )
        if rows
        else None,
        "old_meets_expectation": sum(bool(row.get("old_meets_expectation")) for row in rows),
        "claim_backed_meets_expectation": sum(
            bool(row.get("claim_backed_meets_expectation")) for row in rows
        ),
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
