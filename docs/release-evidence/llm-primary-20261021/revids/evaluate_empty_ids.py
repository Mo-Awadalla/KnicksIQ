#!/usr/bin/env python3
"""Offline before/after for reviewer spans with verdict supported and empty ids.

The defect: the reviewer returns verdict supported for a factual span and drops both
citing arrays, so validate_review fails closed and the user gets the fallback. This
script replays recorded reviewer verdicts (no model calls) through:

- old: the validate_review shipped on codex/llmp-integration (5b585e6), embedded verbatim.
- new: the current validate_review, which attaches claim ids only when every number in the
  span is a declared claim value or claim field and each stated value maps to exactly one
  declared claim.

Two sets:

1. Recorded live review units (head-units.jsonl, labels.json). `as_recorded` is the real
   verdict; `blank_ids` simulates the reported failure by clearing the citing arrays on
   factual and interpretation spans.
2. Numeric mutations of the labeled-correct answers, using the same swap and percent cases
   as tools/release/analyst_gate_mutations.py. Worst case for the new path: the reviewer
   returns supported with empty ids on every span. `new_blank_accepted` on a wrong mutation
   is the acceptance risk this change could add.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/revids/evaluate_empty_ids.py \
      --out docs/release-evidence/llm-primary-20261021/revids/empty-ids-offline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

from analyst_gate_mutations import gate_accepts  # noqa: E402
from analyst_review_base import load_models  # noqa: E402
from analyst_review_replay import load_units  # noqa: E402
from app.services.analyst_review_checks import number_tokens, trusted_numbers  # noqa: E402
from app.services.evidence_contracts import (  # noqa: E402
    AnswerReview,
    AssertionReview,
    ProposedAnswer,
    deterministic_claim_ids,
    split_review_spans,
    validate_review,
)

REVIEWER = ROOT / "docs/release-evidence/llm-primary-20261021/reviewer"
RATIO = Decimal("0.10")


def old_validate_review(
    review: AnswerReview,
    answer: ProposedAnswer,
    claims: dict[str, Any],
    evidence: dict[str, Any],
    spans: list[str] | None = None,
) -> bool:
    """Verbatim codex/llmp-integration 5b585e6 behaviour."""
    if spans is not None:
        if len(review.assertions) != len(spans) or not all(
            item.text.strip() for item in review.assertions
        ):
            return False
    elif "".join(item.text for item in review.assertions) != answer.text:
        return False
    for item in review.assertions:
        if item.verdict != "supported":
            return False
        if item.assertion_type in {"factual", "interpretation"} and not (
            item.supporting_claim_ids or item.supporting_evidence_ids
        ):
            return False
        if not set(item.supporting_claim_ids) <= claims.keys():
            return False
        if not set(item.supporting_evidence_ids) <= evidence.keys():
            return False
    return True


def blank_ids(review: AnswerReview) -> AnswerReview:
    return review.model_copy(
        update={
            "assertions": [
                item.model_copy(update={"supporting_claim_ids": [], "supporting_evidence_ids": []})
                if item.assertion_type in {"factual", "interpretation"}
                else item
                for item in review.assertions
            ]
        }
    )


def synthetic_review(spans: list[str]) -> AnswerReview:
    """Reviewer said supported on every span and dropped every factual citation."""
    return AnswerReview(
        assertions=[
            AssertionReview(
                text=span,
                assertion_type="factual",
                verdict="supported",
                offending_text=None,
                supporting_claim_ids=[],
                supporting_evidence_ids=[],
                reason="Simulated supported verdict without ids.",
            )
            for span in spans
        ]
    )


def recorded_units() -> list[dict[str, Any]]:
    labels = json.loads((REVIEWER / "labels.json").read_text())
    units = load_units([REVIEWER / "head-units.jsonl"], labels)
    rows = []
    for unit_id, record_id, attempt, label in units:
        answer, claims, evidence, _candidates = load_models(attempt)
        review = AnswerReview.model_validate(attempt["parsed"])
        spans = split_review_spans(answer.text)
        blank = blank_ids(review)
        rows.append(
            {
                "unit": unit_id,
                "id": record_id,
                "label": label,
                "spans": len(spans),
                "factual": sum(
                    item.assertion_type in {"factual", "interpretation"}
                    for item in review.assertions
                ),
                "as_recorded": {
                    "old": old_validate_review(review, answer, claims, evidence, spans),
                    "new": validate_review(review, answer, claims, evidence, spans=spans),
                },
                "blank_ids": {
                    "old": old_validate_review(blank, answer, claims, evidence, spans),
                    "new": validate_review(blank, answer, claims, evidence, spans=spans),
                },
                "new_blank_attachable": sum(
                    bool(deterministic_claim_ids(span, answer, claims)) for span in spans
                ),
            }
        )
    return rows


def mutation_rows() -> list[dict[str, Any]]:
    labels = json.loads((REVIEWER / "labels.json").read_text())
    units = load_units([REVIEWER / "head-units.jsonl"], labels)
    rows: list[dict[str, Any]] = []
    for unit_id, record_id, attempt, label in units:
        if label != "correct":
            continue
        answer, claims, evidence, _candidates = load_models(attempt)
        payload = attempt.get("payload") or {}
        trusted = trusted_numbers(claims, evidence, payload.get("capabilities"))
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
                spans = split_review_spans(text)
                review = synthetic_review(spans)
                rows.append(
                    {
                        "unit": unit_id,
                        "id": record_id,
                        "kind": "text_number_swap",
                        "original": token.raw,
                        "replacement": f"{replacement:.{token.decimals}f}",
                        "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
                        "old_blank_accepted": old_validate_review(
                            review, mutated, claims, evidence, spans
                        ),
                        "new_blank_accepted": validate_review(
                            review, mutated, claims, evidence, spans=spans
                        ),
                    }
                )
        used = [use.claim_id for use in answer.claims if use.claim_id in claims]
        if used:
            ratio_id = used[0] + ":ratio"
            ratio_claims = dict(claims)
            ratio_claims[ratio_id] = claims[used[0]].model_copy(
                update={"claim_id": ratio_id, "value": float(RATIO)}
            )
            for label_name, shown in (
                ("control", RATIO * 100),
                *((f"+{k}", RATIO * 100 + k) for k in (1, 5, 40)),
            ):
                text = f"{answer.text} That rate was {shown:.0f}%."
                mutated = answer.model_copy(update={"text": text})
                spans = split_review_spans(text)
                review = synthetic_review(spans)
                rows.append(
                    {
                        "unit": unit_id,
                        "id": record_id,
                        "kind": "percent_of_ratio",
                        "case": label_name,
                        "ratio": str(RATIO),
                        "stated": f"{shown:.0f}%",
                        "gate_accepts": gate_accepts(mutated, ratio_claims, evidence, payload),
                        "old_blank_accepted": old_validate_review(
                            review, mutated, ratio_claims, evidence, spans
                        ),
                        "new_blank_accepted": validate_review(
                            review, mutated, ratio_claims, evidence, spans=spans
                        ),
                    }
                )
    return rows


def summarize(units: list[dict[str, Any]], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    by_label: dict[str, dict[str, int]] = {}
    for label in ("correct", "wrong"):
        selected = [row for row in units if row["label"] == label]
        by_label[label] = {
            "units": len(selected),
            "old_as_recorded": sum(row["as_recorded"]["old"] for row in selected),
            "new_as_recorded": sum(row["as_recorded"]["new"] for row in selected),
            "old_blank": sum(row["blank_ids"]["old"] for row in selected),
            "new_blank": sum(row["blank_ids"]["new"] for row in selected),
            "recovered": sum(
                row["blank_ids"]["new"] and not row["blank_ids"]["old"] for row in selected
            ),
            "recovered_units": [
                row["unit"]
                for row in selected
                if row["blank_ids"]["new"] and not row["blank_ids"]["old"]
            ],
            "still_rejected": [
                row["unit"]
                for row in selected
                if not row["blank_ids"]["new"] and not row["blank_ids"]["old"]
            ],
        }
    wrong = [row for row in mutations if row.get("case") != "control"]
    controls = [row for row in mutations if row.get("case") == "control"]
    return {
        "recorded": by_label,
        "mutations": {
            "wrong_total": len(wrong),
            "gate_accepted": sum(row["gate_accepts"] for row in wrong),
            "old_blank_accepted": sum(row["old_blank_accepted"] for row in wrong),
            "new_blank_accepted": sum(row["new_blank_accepted"] for row in wrong),
            "controls": len(controls),
            "controls_new_blank_accepted": sum(row["new_blank_accepted"] for row in controls),
            "new_blank_accepted_rows": [
                {key: row[key] for key in ("unit", "kind", "original", "replacement")}
                for row in wrong
                if row["new_blank_accepted"]
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).with_name("empty-ids-offline.json"),
    )
    args = parser.parse_args()
    units = recorded_units()
    mutations = mutation_rows()
    artifact = {
        "source_units": str(REVIEWER / "head-units.jsonl"),
        "source_labels": str(REVIEWER / "labels.json"),
        "summary": summarize(units, mutations),
        "units": units,
        "mutation_rows": mutations,
    }
    args.out.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact["summary"], indent=2))


if __name__ == "__main__":
    main()
