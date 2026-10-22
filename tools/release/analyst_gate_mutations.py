"""Offline mutation check of the deterministic reviewer number gate. No model calls.

The live replay (`analyst_review_replay.py --mutations`) skips a candidate the gate already
accepts, so it measures the model reviewer behind the gate, never the gate's own escapes.
This script keeps every candidate and reports the ones the gate accepts:

- text_number_swap: a stated number moved by 1, 2, 3, 7 and 13 display units, skipping
  replacements that equal another trusted value.
- percent_of_ratio: a sibling ratio claim (0.10) added per unit, then a sentence stating a
  wrong percentage of it (+1, +5, +40 points) and, as a control, the right percentage.

The recorded units contain no ratio claims, hence the added one.

    uv run --package knicksiq-api python tools/release/analyst_gate_mutations.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --out docs/release-evidence/llm-primary-20261021/reviewer/gate-mutations.json
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyst_review_base import load_models  # noqa: E402
from analyst_review_replay import load_units  # noqa: E402
from app.services.analyst_review_checks import (  # noqa: E402
    number_tokens,
    review_issues,
    trusted_numbers,
)
from app.services.evidence_contracts import split_review_spans  # noqa: E402

RATIO = Decimal("0.10")


def gate_accepts(answer, claims, evidence, payload) -> bool:
    spans = split_review_spans(answer.text)
    return not review_issues(
        answer,
        spans,
        claims,
        evidence,
        payload.get("capabilities"),
        payload.get("requested_question", ""),
    )


def swaps(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    trusted = trusted_numbers(claims, evidence, payload.get("capabilities"))
    rows = []
    for token in number_tokens(answer.text):
        if token.value < 3:
            continue
        unit = Decimal(1).scaleb(-token.decimals)
        for step in (1, 2, 3, 7, 13):
            replacement = token.value + unit * step
            if any(abs(replacement - value) <= token.tolerance for value in trusted):
                continue
            text = answer.text.replace(token.raw, f"{replacement:.{token.decimals}f}", 1)
            mutated = answer.model_copy(update={"text": text})
            rows.append(
                {
                    "unit": unit_id,
                    "kind": "text_number_swap",
                    "original": token.raw,
                    "replacement": f"{replacement:.{token.decimals}f}",
                    "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
                }
            )
    return rows


def percents(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    used = [use.claim_id for use in answer.claims if use.claim_id in claims]
    if not used:
        return []
    # A sibling ratio claim, so the numbers the answer already states stay explained.
    ratio_id = used[0] + ":ratio"
    claims = dict(claims)
    claims[ratio_id] = claims[used[0]].model_copy(
        update={"claim_id": ratio_id, "value": float(RATIO)}
    )
    rows = []
    for label, shown in (
        ("control", RATIO * 100),
        *((f"+{k}", RATIO * 100 + k) for k in (1, 5, 40)),
    ):
        text = f"{answer.text} That rate was {shown:.0f}%."
        mutated = answer.model_copy(update={"text": text})
        rows.append(
            {
                "unit": unit_id,
                "kind": "percent_of_ratio",
                "case": label,
                "ratio": str(RATIO),
                "stated": f"{shown:.0f}%",
                "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text())
    rows: list[dict[str, Any]] = []
    for unit_id, _, attempt, verdict in load_units([args.records], labels):
        if verdict != "correct":
            continue
        rows += swaps(unit_id, attempt) + percents(unit_id, attempt)
    wrong = [r for r in rows if r.get("case") != "control"]
    controls = [r for r in rows if r.get("case") == "control"]
    summary = {
        "wrong_total": len(wrong),
        "wrong_accepted": sum(r["gate_accepts"] for r in wrong),
        "wrong_accepted_by_kind": {
            kind: sum(r["gate_accepts"] for r in wrong if r["kind"] == kind)
            for kind in ("text_number_swap", "percent_of_ratio")
        },
        "controls": len(controls),
        "controls_rejected": sum(not r["gate_accepts"] for r in controls),
    }
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
