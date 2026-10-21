"""Reviewer packets and mechanical review checks for a captured evaluation run.

Packets show exactly what the scorer binds: the observation digest, the answer
with character offsets, cited runtime references and their mapped canonical
sources, the frozen facts with their fact IDs, and the retrieval traces.
`check` runs the release runner's own validation, so a review that passes here
is mechanically valid; semantic correctness remains the reviewer's judgment.

    uv run --package knicksiq-api python tools/release/evaluation_review_kit.py packet \
        --contract expectations.json --observations obs.json --mapping mapping.json \
        --case exact_statistics-001
    uv run --package knicksiq-api python tools/release/evaluation_review_kit.py check \
        --contract expectations.json --observations obs.json --mapping mapping.json \
        --reviews reviews.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))

from app.evaluation.release_runner import (  # noqa: E402
    _review_assertions,
    digest,
    score_reviewed,
)


def load(args) -> tuple[dict, dict, dict, str]:
    contract = json.loads(args.contract.read_text())
    captured = json.loads(args.observations.read_text())
    mapping = json.loads(args.mapping.read_text())
    return contract, captured, mapping, captured["mode"]


def packet(contract: dict, captured: dict, mapping: dict, case_id: str) -> dict:
    case = next(c for c in contract["cases"] if c["id"] == case_id)
    observation = next(o for o in captured["observations"] if o["case_id"] == case_id)
    response = observation["response"]
    answer = response.get("answer", "")
    citations = []
    for citation in response.get("citations", []):
        metadata = citation.get("metadata") or {}
        ref = metadata.get("evidence_id")
        citations.append(
            {
                "evidence_id": ref,
                "type": citation.get("type"),
                "text": citation.get("claim") or citation.get("title"),
                "mapped_sources": mapping.get(ref, []) if ref else [],
            }
        )
    searches = observation.get("capture", {}).get("searches", [])
    return {
        "case_id": case_id,
        "mode": captured["mode"],
        "question": case["question"],
        "context": case.get("context", []),
        "expected_disposition": case["disposition"],
        "semantic_member": case["semantic_member"],
        "semantic_targets": case.get("semantic_targets", []),
        "context_free_clarification": case.get("context_free_clarification", False),
        "frozen_facts": [{"fact_id": digest(fact), **fact} for fact in case["facts"]],
        "observation_sha256": digest(observation),
        "route": response.get("route"),
        "warnings": response.get("warnings", []),
        "refused": response.get("refused"),
        "follow_up_questions": response.get("follow_up_questions", []),
        "answer": answer,
        "answer_length": len(answer),
        "answer_lines_with_offsets": [
            {"start": start, "end": start + len(line), "text": line}
            for start, line in _lines(answer)
        ],
        "citations": citations,
        "ranked_returned_evidence": list(
            dict.fromkeys(ref for s in searches for ref in s.get("returned_evidence_ids", []))
        ),
        "candidate_evidence": list(
            dict.fromkeys(ref for s in searches for ref in s.get("candidate_evidence_ids", []))
        )[:20],
    }


def _lines(answer: str):
    start = 0
    for line in answer.splitlines(keepends=True):
        yield start, line
        start += len(line)


def check(contract: dict, captured: dict, mapping: dict, reviews: list) -> dict:
    by_case = {o["case_id"]: o for o in captured["observations"]}
    cases = {c["id"]: c for c in contract["cases"]}
    problems = []
    for review in reviews:
        case_id = review.get("case_id")
        if case_id not in cases:
            problems.append({"case_id": case_id, "problem": "unknown case"})
            continue
        observation = by_case[case_id]
        if review.get("observation_sha256") != digest(observation):
            problems.append({"case_id": case_id, "problem": "observation_sha256 mismatch"})
        if not _review_assertions(
            cases[case_id], observation, review.get("assertions", []), mapping
        ):
            problems.append(
                {
                    "case_id": case_id,
                    "problem": "assertion spans invalid: must be contiguous from 0 to the full "
                    "answer length; factual spans need frozen fact IDs and cited evidence IDs "
                    "whose mapped sources support each fact; answer cases must cover every fact",
                }
            )
    result = score_reviewed(contract, captured["observations"], reviews, mapping, captured["mode"])
    reviewed = {r.get("case_id") for r in reviews}
    invalid = [
        f["case_id"]
        for f in result["failures"]
        if f["case_id"] in reviewed and not f["review_valid"]
    ]
    return {"reviews": len(reviews), "invalid_reviews": invalid, "problems": problems}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["packet", "check"])
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    contract, captured, mapping, _mode = load(args)
    if args.command == "packet":
        ids = args.case or [c["id"] for c in contract["cases"]]
        print(json.dumps([packet(contract, captured, mapping, i) for i in ids], indent=1))
    else:
        if args.reviews is None:
            parser.error("check requires --reviews")
        reviews = json.loads(args.reviews.read_text())
        print(json.dumps(check(contract, captured, mapping, reviews), indent=1))


if __name__ == "__main__":
    main()
