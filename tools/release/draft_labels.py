"""Independently review all 120 fixed questions against a pinned canonical archive.

Produces proposed labels and explicit disagreements, never owner-approved gold.
Does not import the analyst, retrieval pipeline, or evaluation response output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# These standalone CLIs also support module execution and file-based loading.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from label_canonical import (
    ALL_STAR_END,
    ALL_STAR_SOURCE,
    Canonical,
)
from label_canonical import (
    digest as digest,
)
from label_case_review import CaseReview

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "release-artifacts/2025-26/release-corrected-unreviewed.json"
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
OUTPUT = ROOT / "docs/release-evidence/evaluation-label-review-20260907"


def review_cases(payload, cases):
    canonical = Canonical(payload)
    common = {
        "season_scope": "2025-26 regular season and postseason unless explicitly restricted",
        "player_rate_denominator": (
            "appearances with minutes > 0; last N player games means last N appearances"
        ),
        "all_star_boundary": {"date_exclusive": ALL_STAR_END, "source": ALL_STAR_SOURCE},
        "no_api_outputs_used": True,
        "owner_approval": None,
    }
    return [CaseReview(canonical).review_case(case) for case in cases], common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    raw = args.baseline.read_bytes()
    payload = json.loads(raw)
    cases = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    labels, policy = review_cases(payload, cases)
    identity = {
        "baseline_file_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_data_sha256": digest(
            {k: v for k, v in payload["data"].items() if k != "reports"}
        ),
        "questions_file_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "data_version": payload["manifest"]["version"],
    }
    for label in labels:
        label.update(identity)
    args.output.mkdir(parents=True, exist_ok=True)
    labels_path = args.output / "labels.jsonl"
    labels_path.write_text(
        "".join(json.dumps(label, sort_keys=True, separators=(",", ":")) + "\n" for label in labels)
    )
    summary = {
        "schema_version": 1,
        "identity": identity,
        "policy": policy,
        "case_count": len(labels),
        "original_category_counts": dict(Counter(c["category"] for c in labels)),
        "proposed_dispositions": dict(Counter(c["proposed_label"]["disposition"] for c in labels)),
        "agent_reviewed": len(labels),
        "owner_approved": 0,
        "gold_labels_eligible": False,
        "labels_file_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "discrepancies": [
            {
                "id": c["id"],
                "question": c["question"],
                "issues": c["discrepancies"],
                "proposed_label": c["proposed_label"],
            }
            for c in labels
            if c["discrepancies"]
        ],
        "blocking_integration_issues": [
            (
                "Canonical NBA IDs must map to verified candidate retrieval evidence IDs; "
                "current runtime IDs may differ."
            ),
            (
                "Accepted phrase variants must be batch-reviewed. Exact English strings and "
                "numeric rounding cannot be inferred from a dry-run answer."
            ),
            (
                "Do not treat clarified questions as removed semantic tests or claim Recall@5"
                " from a smaller replacement set."
            ),
            (
                "Original question, category, answerable and route fields are preserved. "
                "Proposed adjudications do not silently rewrite the evaluation set."
            ),
            (
                "The evaluation harness currently treats all answerable=false cases as "
                "refused and cannot distinguish correct clarification from inappropriate "
                "refusal."
            ),
        ],
    }
    (args.output / "review.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "# Evaluation label review",
        "",
        f"All {len(labels)} fixed questions reviewed against canonical rows. "
        "Owner approvals: **0**. Gold-label eligibility: **blocked**.",
        "",
        f"Proposed dispositions: {json.dumps(summary['proposed_dispositions'], sort_keys=True)}.",
        "",
        (
            "Original questions, categories and expected labels are preserved. "
            "Recommendations below are explicit owner adjudications, not relabelled "
            "passing results."
        ),
        "",
        (
            "Player averages use appearances; last-N player windows use appearances "
            "rather than team games. All-Star boundary is after February 15, 2026, "
            "verified against [NBA All-Star](https://www.nba.com/allstar/2026/). All "
            "arithmetic uses canonical archive rows."
        ),
        "",
        (
            "Every factual claim has typed values, metric scope, canonical source IDs and"
            " source-row hashes in labels.jsonl. These IDs still need mapping to the "
            "verified runtime/index; accepted prose variants and rounding are pending "
            "owner batch review."
        ),
        "",
        "| Question | Proposed behavior | Canonical facts / decision |",
        "|---|---|---|",
    ]
    for label in labels:
        p = label["proposed_label"]
        detail = "; ".join(p["required_facts"] or p["notes"])
        lines.append(
            f"| {label['id']}: {label['question']} | {p['disposition']} | "
            f"{detail.replace('|', '/')} |"
        )
    (args.output / "review.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "case_count",
                    "proposed_dispositions",
                    "agent_reviewed",
                    "owner_approved",
                    "labels_file_sha256",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
