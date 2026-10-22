"""Aggregate the three arm directories into one comparison table.

Reads only committed artifacts: `metrics.json`, `ledger.jsonl`, `calls_normalized.jsonl`,
`trial{1,2}.scored.jsonl` and the factual audit's `rows.jsonl` under `audit/trial{1,2}/`.
Writes `summary.json` and prints the markdown table used in the README.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ARMS = ("A", "B", "C")


def percentile(values: list[float], fraction: float, digits: int = 1) -> float:
    """Nearest rank, the method in tools/release/latency_stats.py."""
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], digits)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def arm_metrics(arm: str) -> dict[str, Any]:
    root = HERE / f"arm-{arm}"
    metrics = json.loads((root / "metrics.json").read_text())
    rows = load_jsonl(root / "ledger.jsonl")
    calls = load_jsonl(root / "calls_normalized.jsonl")
    failures: dict[str, int] = {}
    for row in rows:
        for failure in row.get("failures") or []:
            key = f"{failure['stage']}:{failure['error_type']}"
            failures[key] = failures.get(key, 0) + 1
    reasoning = sum(int(call.get("reasoning_tokens") or 0) for call in calls)
    reasoning_by_stage: dict[str, int] = {}
    for call in calls:
        stage = call.get("stage") or "unknown"
        reasoning_by_stage[stage] = reasoning_by_stage.get(stage, 0) + int(
            call.get("reasoning_tokens") or 0
        )
    per_question_reasoning = [int(call.get("reasoning_tokens") or 0) for call in calls]
    audit = {"found": 0, "verified": 0, "wrong": 0, "unverified": 0, "checked": 0}
    audit_responses_with_wrong = 0
    audit_rows = 0
    for trial in (1, 2):
        for row in load_jsonl(root / "audit" / f"trial{trial}" / "rows.jsonl"):
            audit_rows += 1
            for key in audit:
                audit[key] += int(row.get(key) or 0)
            if int(row.get("wrong") or 0):
                audit_responses_with_wrong += 1
    unsupported = [row for row in rows if not row["answerable"]]
    declined = [row for row in unsupported if row["outcome"] == "validated_declined"]
    # A call cancelled by the analyst deadline records no metadata and no error; it is not an
    # empty model output, so it is counted separately.
    cancelled_calls = sum(1 for call in calls if not call.get("protocol"))
    truncated_calls = sum(1 for call in calls if str(call.get("finish_reason")) == "length")
    empty_output_calls = sum(
        1
        for call in calls
        if call.get("protocol")
        and str(call.get("content_kind")) in {"empty_string", "null"}
        and not call.get("error")
    )
    model_errors = sum(1 for call in calls if call.get("error"))
    scored = [
        row
        for trial in (1, 2)
        for row in load_jsonl(root / f"trial{trial}.scored.jsonl")
    ]
    by_category: dict[str, dict[str, int]] = {}
    for row in scored:
        bucket = by_category.setdefault(row["category"], {"questions": 0, "meets": 0})
        bucket["questions"] += 1
        bucket["meets"] += int(row["meets_expectation"])
    return {
        "arm": arm,
        "settings": metrics["settings"],
        "questions": metrics["questions"],
        "trials": metrics["trials"],
        "honest": {
            f"trial_{trial}": metrics["by_trial"][str(trial)]["meets_expectation"]
            for trial in (1, 2)
        },
        "honest_total": sum(
            metrics["by_trial"][str(trial)]["meets_expectation"] for trial in (1, 2)
        ),
        "honest_spread": metrics["spread_meets_expectation"],
        "claim_backed_total": sum(
            metrics["by_trial"][str(trial)]["claim_backed"] for trial in (1, 2)
        ),
        "validated": sum(metrics["by_trial"][str(trial)]["validated"] for trial in (1, 2)),
        "by_category": {
            name: f"{bucket['meets']}/{bucket['questions']}"
            for name, bucket in sorted(by_category.items())
        },
        "outcomes": metrics["outcomes"],
        "failed_stages": failures,
        "failed_stages_total": sum(failures.values()),
        "calls": metrics["calls"],
        "call_errors": metrics["calls"]["errors"],
        "truncated_calls": truncated_calls,
        "empty_output_calls": empty_output_calls,
        "cancelled_calls": cancelled_calls,
        "model_error_calls": model_errors,
        "latency": {
            "p50_ms": metrics["latency"]["p50_ms"],
            "p95_ms": metrics["latency"]["p95_ms"],
            "mean_ms": metrics["latency"]["mean_ms"],
            "by_stage": {
                name: {
                    "calls": value["calls"],
                    "p50_ms": value["p50_ms"],
                    "p95_ms": value["p95_ms"],
                }
                for name, value in metrics["latency"]["by_stage"].items()
                if value["calls"]
            },
        },
        "reasoning_tokens": {
            "total": reasoning,
            "by_stage": reasoning_by_stage,
            "per_call_p50": percentile([float(v) for v in per_question_reasoning], 0.5)
            if per_question_reasoning
            else None,
            "per_call_p95": percentile([float(v) for v in per_question_reasoning], 0.95)
            if per_question_reasoning
            else None,
            "per_question": round(reasoning / len(rows), 1) if rows else None,
        },
        "cost": {
            "total_usd": metrics["cost"]["ledger_delta_total_usd"],
            "per_question_usd": metrics["cost"]["mean_per_question_usd"],
            "p95_per_question_usd": metrics["cost"]["p95_per_question_usd"],
            "reconciles": metrics["cost"]["reconciles"],
            "monthly_capacity_at_2_usd": metrics["cost"]["monthly_capacity_at_2_usd"],
        },
        "unsupported": {
            "questions": len(unsupported),
            "declined": len(declined),
            "declined_ids": [row["id"] for row in declined],
            "not_declined": [
                {"id": row["id"], "outcome": row["outcome"]}
                for row in unsupported
                if row["outcome"] != "validated_declined"
            ],
        },
        "audit": {**audit, "responses": audit_rows, "responses_with_wrong": audit_responses_with_wrong,
                  "coverage": round((audit["verified"] + audit["wrong"]) / audit["found"], 4)
                  if audit["found"]
                  else None},
        "ledger_reconciles_all": all(row["reconciles"] for row in rows),
        "mean_calls_per_question": metrics["calls"]["mean_per_question"],
    }


def main() -> None:
    arms = {arm: arm_metrics(arm) for arm in ARMS}
    (HERE / "summary.json").write_text(json.dumps(arms, indent=2) + "\n")
    header = (
        "| Metric | A (none) | B (low) | C (medium) |\n| --- | ---: | ---: | ---: |\n"
    )
    rows = [
        ("Honest, 2 trials / 60", "honest_total", None),
        ("Honest trial 1 / 30", "trial_1", "honest"),
        ("Honest trial 2 / 30", "trial_2", "honest"),
        ("Spread", "honest_spread", None),
        ("Claim-backed / 60", "claim_backed_total", None),
        ("llm_validated / 60", "validated", None),
        ("Failed model stages", "failed_stages_total", None),
        ("Truncated calls (length)", "truncated_calls", None),
        ("Empty-output calls", "empty_output_calls", None),
        ("Deadline-cancelled calls", "cancelled_calls", None),
        ("Provider call errors", "call_errors", None),
        ("Audit wrong atoms", "wrong", "audit"),
        ("Audit verified atoms", "verified", "audit"),
        ("Audit coverage", "coverage", "audit"),
        ("Unsupported declined", "declined", "unsupported"),
        ("Unsupported questions", "questions", "unsupported"),
        ("p50 latency ms", "p50_ms", "latency"),
        ("p95 latency ms", "p95_ms", "latency"),
        ("Reasoning tokens / question", "per_question", "reasoning_tokens"),
        ("Cost / question USD", "per_question_usd", "cost"),
        ("Monthly capacity at $2", "monthly_capacity_at_2_usd", "cost"),
        ("Mean calls / question", "mean_calls_per_question", None),
    ]
    print(header)
    for label, key, parent in rows:
        cells = []
        for arm in ARMS:
            value = arms[arm][parent][key] if parent else arms[arm][key]
            if key == "coverage" and value is not None:
                value = f"{value:.2%}"
            cells.append("n/a" if value is None else str(value))
        print(f"| {label} | " + " | ".join(cells) + " |")
    print()
    for arm in ARMS:
        print(f"arm {arm}: outcomes={arms[arm]['outcomes']}")
        print(f"arm {arm}: failed_stages={arms[arm]['failed_stages']}")
        print(f"arm {arm}: by_category={arms[arm]['by_category']}")
        print(f"arm {arm}: reasoning_by_stage={arms[arm]['reasoning_tokens']['by_stage']}")
        print(f"arm {arm}: declines={arms[arm]['unsupported']['declined_ids']}"
              f" not_declined={arms[arm]['unsupported']['not_declined']}")
        print(f"arm {arm}: stage_latency={arms[arm]['latency']['by_stage']}")


if __name__ == "__main__":
    main()
