"""Build the 120-case evaluation expectations contract from reviewed labels.

The release runner scores only against a frozen contract with separate
hash-bound owner approval. This builder keeps the original questions and
cohort; unresolved adjudications leave the contract as a draft.

    uv run --package knicksiq-api python tools/release/build_eval_contract.py \
        --adjudications ADJUDICATIONS.json --output expectations.json

ADJUDICATIONS.json maps a case id to `semantic_targets` and `decision_basis`.
It may also override `disposition` and `facts` or set
`context_free_clarification`. Facts must use the existing canonical-fact shape.
A reviewer may prepare adjudications, but the owner separately approves the
exact frozen contract hash. The builder never invents targets or facts.

A context-free clarification has empty conversation context and no candidate
games. Its entry has empty `semantic_targets`, sets
`context_free_clarification: true`, and expects `clarify`.

Retrieval answers use Recall@k with k = max(5, number of targets), so no target
list is capped to fit the metric.
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


def _valid_canonical_facts(facts: object) -> bool:
    if not isinstance(facts, list):
        return False
    for fact in facts:
        if not isinstance(fact, dict):
            return False
        evidence_ids = fact.get("canonical_evidence_ids")
        if (
            not isinstance(fact.get("metric"), str)
            or not fact["metric"].strip()
            or not isinstance(fact.get("scope"), str)
            or not fact["scope"].strip()
            or "value" not in fact
            or not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(not isinstance(item, str) or not item for item in evidence_ids)
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            return False
    return True


def build(adjudications: dict[str, dict]) -> tuple[dict, list[dict]]:
    questions = read_jsonl(QUESTIONS)
    labels = {label["id"]: label for label in read_jsonl(LABELS)}
    if not isinstance(adjudications, dict):
        raise ValueError("Adjudications must be an object")
    question_ids = {question["id"] for question in questions}
    if set(adjudications) - question_ids:
        raise ValueError("Adjudications contain unknown case IDs")
    allowed_adjudication_fields = {
        "semantic_targets",
        "decision_basis",
        "disposition",
        "facts",
        "context_free_clarification",
    }
    required_adjudication_fields = {"semantic_targets", "decision_basis"}
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
        problems = []
        if question["id"] in adjudications:
            adjudication = adjudications[question["id"]]
            if not isinstance(adjudication, dict):
                problems.append("adjudication must be an object")
                adjudication = {}
            unknown = set(adjudication) - allowed_adjudication_fields
            missing = required_adjudication_fields - set(adjudication)
            if unknown:
                problems.append("adjudication has unsupported fields")
            if missing:
                problems.append("adjudication is missing required fields")
            if "semantic_targets" in adjudication:
                targets = adjudication["semantic_targets"]
                if (
                    not isinstance(targets, list)
                    or any(not isinstance(item, str) or not item for item in targets)
                    or len(targets) != len(set(targets))
                ):
                    problems.append("adjudicated targets must be unique nonempty strings")
                else:
                    case["semantic_targets"] = targets
            if "decision_basis" in adjudication:
                basis = adjudication["decision_basis"]
                if not isinstance(basis, str) or not basis.strip():
                    problems.append("adjudication decision_basis must be a nonempty string")
                else:
                    case["decision_basis"] = basis
            if "disposition" in adjudication:
                disposition = adjudication["disposition"]
                if not isinstance(disposition, str) or disposition not in {
                    "answer",
                    "clarify",
                    "refuse",
                }:
                    problems.append("adjudicated disposition is invalid")
                else:
                    case["disposition"] = disposition
            if "facts" in adjudication:
                facts = adjudication["facts"]
                if not _valid_canonical_facts(facts):
                    problems.append("adjudicated facts must use the canonical fact shape")
                else:
                    case["facts"] = facts
            if "context_free_clarification" in adjudication:
                context_free = adjudication["context_free_clarification"]
                if type(context_free) is not bool:
                    problems.append("context_free_clarification must be boolean")
                elif context_free:
                    case["context_free_clarification"] = True
        context_free = case.get("context_free_clarification") is True
        targets = case.get("semantic_targets", [])
        if (
            not isinstance(targets, list)
            or any(not isinstance(item, str) or not item for item in targets)
            or len(targets) != len(set(targets))
        ):
            problems.append("semantic targets must be unique nonempty strings")
        if context_free and (not semantic or case["disposition"] != "clarify"):
            problems.append("context-free clarification on a case that does not expect clarify")
        if context_free and case.get("context"):
            problems.append("context-free clarification cannot discard conversation context")
        if context_free and targets:
            problems.append("context-free clarification must not name retrieval targets")
        if semantic and not targets and not context_free:
            problems.append("semantic member without a retrieval target")
        if not _valid_canonical_facts(case["facts"]):
            problems.append("facts must use the canonical fact shape")
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
