"""Offline false-refusal and missed-refusal rates for the pre-model refusal gate.

The gate is pure text, so this measurement needs no database, Redis or provider call.
Run it before and after a policy change with the same committed corpora:

    uv run --package knicksiq-api python tools/release/analyst_refusal_rates.py \
      --label after --out docs/release-evidence/llm-primary-20261021/safety/refusal-rates-after.json

Corpora live in tools/release/refusal_corpora/. Benign questions are answerable from the
archive and contain a word the old gate treated as live, future, injury or betting text.
Adversarial questions carry the routing expectation: pre_model_refusal for unambiguous
categories, analyst_decline for questions the analyst must handle with coverage labels.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.api import analysis_policy

CORPORA = Path(__file__).resolve().parent / "refusal_corpora"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (CORPORA / name).read_text().splitlines() if line.strip()]


def rate(hit: int, total: int) -> float:
    return round(hit / total, 4) if total else 0.0


def measure(label: str) -> dict:
    gate = analysis_policy._requires_pre_model_refusal
    category_of = getattr(analysis_policy, "pre_model_refusal_category", None)
    categories = getattr(analysis_policy, "PRE_MODEL_REFUSAL_CATEGORIES", ())
    benign_cases = []
    for row in load("benign_archive.jsonl"):
        refused = gate(row["question"])
        benign_cases.append(
            {
                **row,
                "gate_refused": refused,
                "gate_category": category_of(row["question"]) if category_of else None,
            }
        )
    adversarial_cases = []
    for row in load("adversarial_unsupported.jsonl"):
        refused = gate(row["question"])
        adversarial_cases.append(
            {
                **row,
                "gate_refused": refused,
                "gate_category": category_of(row["question"]) if category_of else None,
            }
        )
    must = [case for case in adversarial_cases if case["expected"] == "pre_model_refusal"]
    owned = [case for case in adversarial_cases if case["expected"] == "analyst_decline"]
    refused_benign = sum(case["gate_refused"] for case in benign_cases)
    refused_must = sum(case["gate_refused"] for case in must)
    refused_owned = sum(case["gate_refused"] for case in owned)
    missed = [case["id"] for case in must if not case["gate_refused"]]
    over = [case["id"] for case in owned if case["gate_refused"]]
    report = {
        "schema": "analyst-refusal-rates-v1",
        "label": label,
        "generated_at": datetime.now(UTC).isoformat(),
        "gate": "app.api.analysis_policy._requires_pre_model_refusal",
        "categories": [category.name for category in categories],
        "benign": {
            "total": len(benign_cases),
            "gate_refused": refused_benign,
            "allowed": len(benign_cases) - refused_benign,
            "false_refusal_rate": rate(refused_benign, len(benign_cases)),
            "allowed_rate": rate(len(benign_cases) - refused_benign, len(benign_cases)),
        },
        "adversarial": {
            "total": len(adversarial_cases),
            "must_refuse_pre_model": {
                "total": len(must),
                "refused": refused_must,
                "missed": len(missed),
                "missed_refusal_rate": rate(len(missed), len(must)),
            },
            "analyst_owned": {
                "total": len(owned),
                "gate_refused": refused_owned,
                "allowed": len(owned) - refused_owned,
                "over_refusal_rate": rate(refused_owned, len(owned)),
                "routed_to_analyst_rate": rate(len(owned) - refused_owned, len(owned)),
            },
            "missed_ids": missed,
            "over_refused_ids": over,
        },
        "category_counts": dict(
            Counter(case["category"] for case in adversarial_cases if case["gate_refused"])
        ),
        "cases": {"benign": benign_cases, "adversarial": adversarial_cases},
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="current", help="before / after / current")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = measure(args.label)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    benign = report["benign"]
    must = report["adversarial"]["must_refuse_pre_model"]
    owned = report["adversarial"]["analyst_owned"]
    print(
        f"{args.label}: benign false refusals {benign['gate_refused']}/{benign['total']} "
        f"({benign['false_refusal_rate']}); must-refuse missed "
        f"{must['missed']}/{must['total']} ({must['missed_refusal_rate']}); "
        f"analyst-owned over-refused {owned['gate_refused']}/{owned['total']} "
        f"({owned['over_refusal_rate']})"
    )
    if report["categories"]:
        print("categories:", ", ".join(report["categories"]))


if __name__ == "__main__":
    main()
