"""Provider-call statistics for the reviewer replay artifact.

Kept separate so `analyst_review_replay.py` stays inside the repository's authored-file
size limit. No provider call happens here.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; no interpolation, so every value is an observed call."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return round(ordered[index], 1)


def reviewer_stats(replay: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Intended vs served model, token cap, latency and cost across all head trials."""
    provider_calls: list[dict[str, Any]] = []
    finals: Counter = Counter()
    for entry in replay["results"].values():
        for outcome in entry["head"]:
            finals[outcome["outcome"]] += 1
            first = outcome.get("first_attempt")
            if first:
                provider_calls.append(first)
            provider_calls.append(outcome)
    calls = [call for call in provider_calls if call.get("metadata")]
    latencies = [call["latency_ms"] for call in calls if call.get("latency_ms") is not None]
    costs = [(call["metadata"].get("usage") or {}).get("cost") for call in calls]
    priced_costs = [cost for cost in costs if cost is not None]
    return {
        "reviewer_model_requested": getattr(settings, "analyst_review_model", None),
        "reviewer_max_tokens": getattr(settings, "analyst_review_max_tokens", None),
        "requested_models": dict(Counter(call.get("requested_model") for call in calls)),
        "served_models": dict(Counter(call["metadata"].get("model") for call in calls)),
        "protocols": dict(Counter(call["metadata"].get("protocol") for call in calls)),
        "providers": dict(Counter(call["metadata"].get("provider") for call in calls)),
        "observed_max_tokens": dict(Counter(call["metadata"].get("max_tokens") for call in calls)),
        "provider_calls": len(calls),
        "malformed_reviews": finals.get("malformed_review_json", 0),
        "retried_trials": sum(1 for outcome in provider_calls if outcome.get("retried")),
        "cost_usd": round(sum(priced_costs), 6),
        "cost_per_review": round(sum(priced_costs) / len(calls), 6) if calls else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "samples": len(latencies),
        },
        "outcomes": dict(finals),
    }
