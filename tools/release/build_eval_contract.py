"""Build the 120-case evaluation expectations contract from the agent-reviewed label package.

The release runner (`app.evaluation.release_runner`) scores only against a frozen contract that the
owner has approved by its SHA-256. This builder makes that contract from the existing proposals
without changing any question, category or disposition. Cases the proposals cannot settle stay
`unresolved`, and the contract stays a `draft`, until the owner supplies an adjudication for each.

    uv run --package knicksiq-api python tools/release/build_eval_contract.py \
        --adjudications ADJUDICATIONS.json --output expectations.json

ADJUDICATIONS.json maps a case id to {"semantic_targets": [...], "decision_basis": "..."}. Only the
owner writes it. The builder never invents a target. A semantic case ruled a context-free
clarification (for example "that game" with no earlier game) has no candidate games: its entry has
"semantic_targets": [] and "context_free_clarification": true, and the case must expect `clarify`.

Retrieval is scored as Recall@k with k = max(5, number of targets), so a question's full scope is
never capped to fit the metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
LABELS = ROOT / "docs/release-evidence/evaluation-label-review-20260907/labels.jsonl"
SCORING_VERSION = "release-review-v2"
TOP_K = 5


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build(adjudications: dict[str, dict]) -> tuple[dict, list[dict]]:
    questions = read_jsonl(QUESTIONS)
    labels = {label["id"]: label for label in read_jsonl(LABELS)}
    cases, unresolved = [], []
    for question in questions:
        label = labels[question["id"]]
        if label["question"] != question["question"]:
            raise ValueError(f"Label question changed: {question['id']}")
        proposal = label["proposed_label"]
        semantic = question["answerable"] and question.get("expected_route") == "retrieval_rag"
        case = {
            "id": question["id"],
            "category": question["category"],
            "question": question["question"],
            "context": question.get("context", []),
            "semantic_member": semantic,
            "disposition": proposal["disposition"],
            "facts": proposal["canonical_facts"],
            "decision_status": "settled",
            "decision_basis": " ".join(
                [
                    "Agent-reviewed proposal from canonical rows, no application answer used.",
                    *proposal.get("notes", []),
                ]
            ),
        }
        if semantic:
            case["semantic_targets"] = proposal["canonical_evidence_ids"]
        adjudication = adjudications.get(question["id"])
        if adjudication:
            case["semantic_targets"] = adjudication["semantic_targets"]
            case["decision_basis"] = adjudication["decision_basis"]
            if adjudication.get("context_free_clarification") is True:
                case["context_free_clarification"] = True
        context_free = case.get("context_free_clarification", False)
        problems = []
        if context_free and (not semantic or case["disposition"] != "clarify"):
            problems.append("context-free clarification on a case that does not expect clarify")
        if context_free and case.get("semantic_targets"):
            problems.append("context-free clarification must not name retrieval targets")
        if semantic and not case.get("semantic_targets") and not context_free:
            problems.append("semantic member without a retrieval target")
        if case["disposition"] == "answer" and not case["facts"]:
            problems.append("answer disposition without canonical facts")
        if problems:
            case["decision_status"] = "unresolved"
            unresolved.append(
                {"id": case["id"], "question": case["question"], "problems": problems}
            )
        cases.append(case)
    # Best possible mean Recall@k. With k = max(TOP_K, targets) every settled case can reach 1, so
    # the ceiling falls below 1 only while some semantic case is unresolved.
    semantic = [c for c in cases if c["semantic_member"]]
    ceiling = sum(
        0.0
        if c["decision_status"] != "settled"
        else 1.0
        if c.get("context_free_clarification")
        else min(1.0, max(TOP_K, len(c["semantic_targets"])) / len(c["semantic_targets"]))
        for c in semantic
    ) / len(semantic)
    contract = {
        "version": 1,
        "status": "draft" if unresolved else "frozen",
        "recall_ceiling": round(ceiling, 4),
        "scoring_version": SCORING_VERSION,
        "questions_sha256": file_hash(QUESTIONS),
        "labels_sha256": file_hash(LABELS),
        "cases": cases,
    }
    return contract, unresolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path)
    args = parser.parse_args()
    adjudications = json.loads(args.adjudications.read_text()) if args.adjudications else {}
    contract, unresolved = build(adjudications)
    args.output.write_text(json.dumps(contract, indent=1, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": contract["status"],
                "expectations_sha256": file_hash(args.output),
                "recall_ceiling": contract["recall_ceiling"],
                "unresolved": unresolved,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
