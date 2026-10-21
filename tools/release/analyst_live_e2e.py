"""End-to-end check of the llm_primary analyst against a real provider and a restored release.

Live mode sends questions through the in-process FastAPI app (same code path as production) and
records the full response payload. Offline mode re-scores a committed responses artifact without
the provider. Both modes run the deterministic checks in analyst_scoring.py and write one JSONL
row per question plus a category table.

    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py --out report.json
    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
        --responses old.responses.jsonl --out rescored.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyst_scoring import score_response  # noqa: E402
from archive_values import build as build_archive_values  # noqa: E402
from archive_values import scoped_corpus

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
HELDOUT = ROOT / "apps/api/app/evaluation/heldout_questions.jsonl"


class FailureCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "analyst_execution_failed" in record.getMessage():
            self.records.append(
                {
                    "error_type": getattr(record, "error_type", None),
                    "stage": getattr(record, "stage", None),
                }
            )


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sample(rows: list[dict], per_category: int, all_rows: bool) -> list[dict]:
    if all_rows:
        return [row for row in rows if row["category"] != "follow_ups"]
    seen: collections.Counter[str] = collections.Counter()
    picked = []
    for row in rows:
        if row["category"] == "follow_ups":
            continue
        if seen[row["category"]] < per_category:
            seen[row["category"]] += 1
            picked.append(row)
    return picked


DECLINE = re.compile(
    r"\b(i can(?:'|’)?t|i cannot|can(?:'|’)?t (?:give|provide|answer|predict|verify)|"
    r"cannot (?:give|provide|answer|predict)|not able to|unable to|do(?:es)? not (?:include|"
    r"cover|contain)|doesn(?:'|’)?t (?:include|cover|contain)|no (?:live|future|current))",
    re.I,
)


def classify(body: dict, failures: list[dict]) -> str:
    if body.get("llm_validated"):
        return "validated_declined" if DECLINE.search(body.get("answer") or "") else "validated"
    if failures:
        return f"failed:{failures[-1]['stage']}:{failures[-1]['error_type']}"
    warnings = " ".join(body.get("warnings") or [])
    if "evidence review" in warnings:
        return "fallback:review_rejected"
    if "could not be verified" in warnings:
        return "fallback:unverified"
    return "fallback:other"


def old_meets_expectation(case: dict, outcome: str) -> bool:
    """The pre-existing screen, kept only for the old-versus-new gap."""
    if case["answerable"]:
        return outcome == "validated"
    return outcome == "validated_declined"


def score(case: dict, response: dict, archive) -> dict:
    scoped = scoped_corpus(archive, case.get("question", ""), case, response.get("answer", ""))
    best = score_response(
        case,
        response,
        universe=archive.universe,
        archive=archive,
        scoped=scoped,
        strict=True,
        require_claims=False,
    )
    proof = score_response(
        case,
        response,
        universe=archive.universe,
        archive=archive,
        scoped=scoped,
        strict=True,
        require_claims=True,
    )
    best["claim_backed_meets_expectation"] = proof["meets_expectation"]
    best["claim_backed_failures"] = proof["failures"]
    best["old_meets_expectation"] = bool(
        response.get(
            "old_meets_expectation", old_meets_expectation(case, response.get("outcome", ""))
        )
    )
    return best


async def run_live(cases: list[dict], archive, timeout: float) -> list[dict]:
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    app = create_app()
    results = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", timeout=timeout
        ) as client:
            for case in cases:
                capture.records.clear()
                response = await client.post(
                    "/analysis/query",
                    json={
                        "question": case["question"],
                        "season": "2025-26",
                        "turn_id": "e2e-" + uuid.uuid4().hex,
                        "expected_revision": 0,
                    },
                )
                body = response.json() if response.status_code == 200 else {}
                outcome = (
                    classify(body, capture.records) if body else f"http_{response.status_code}"
                )
                record = {
                    "id": case["id"],
                    "category": case["category"],
                    "answerable": case["answerable"],
                    "question": case["question"],
                    "outcome": outcome,
                    "old_meets_expectation": old_meets_expectation(case, outcome),
                    "answer": body.get("answer") or "",
                    "citations": body.get("citations") or [],
                    "warnings": body.get("warnings") or [],
                    "refused": body.get("refused", False),
                    "degraded": body.get("degraded", False),
                    "llm_validated": body.get("llm_validated", False),
                    "route": body.get("route"),
                    "follow_up_questions": body.get("follow_up_questions") or [],
                    "tool_calls": body.get("tool_calls") or [],
                    "data_version": body.get("data_version"),
                    "status_code": response.status_code,
                }
                results.append({**record, "score": score(case, record, archive)})
    return results


def run_offline(cases: list[dict], responses_path: Path, archive) -> list[dict]:
    by_id = {case["id"]: case for case in cases}
    results = []
    for line in responses_path.read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        case = by_id.get(raw["id"]) or {
            "id": raw["id"],
            "category": raw["category"],
            "answerable": raw["answerable"],
            "question": raw["question"],
            "required_facts": [],
            "required_entities": [],
            "required_phrases": [],
        }
        reduced = isinstance(raw.get("citations"), int)
        record = {
            **raw,
            "outcome": raw.get("outcome", "unknown"),
            "old_meets_expectation": raw.get(
                "old_meets_expectation",
                raw.get("meets_expectation", old_meets_expectation(case, raw.get("outcome", ""))),
            ),
            "llm_validated": raw.get(
                "llm_validated", raw.get("outcome") in {"validated", "validated_declined"}
            ),
            "degraded": str(raw.get("outcome", "")).startswith(("fallback", "failed", "http_")),
            "citations_reduced": reduced,
            "reconstructed_fields": reduced or "llm_validated" not in raw,
        }
        results.append({**record, "score": score(case, record, archive)})
    return results


def summarize(mode: str, dataset: str, results: list[dict]) -> dict:
    by_category: dict[str, dict] = {}
    for item in results:
        score_row = item["score"]
        bucket = by_category.setdefault(
            score_row["category"],
            {"questions": 0, "old": 0, "new": 0, "claim_backed": 0},
        )
        bucket["questions"] += 1
        bucket["old"] += int(score_row["old_meets_expectation"])
        bucket["new"] += int(score_row["meets_expectation"])
        bucket["claim_backed"] += int(score_row["claim_backed_meets_expectation"])
    failures: collections.Counter[str] = collections.Counter()
    for item in results:
        for failure in item["score"]["failures"]:
            failures[failure.split(":")[0]] += 1
    answerable = [item for item in results if item["score"]["answerable"]]
    unsupported = [item for item in results if not item["score"]["answerable"]]
    old = sum(int(item["score"]["old_meets_expectation"]) for item in results)
    new = sum(int(item["score"]["meets_expectation"]) for item in results)
    backed = sum(int(item["score"]["claim_backed_meets_expectation"]) for item in results)
    return {
        "scope": (
            "meets_expectation now requires: not declined or clarification, validated delivery, "
            "substantive content, no unbacked number or entity, required facts present, no echo, "
            "and no unbacked causal hedge. claim_backed additionally requires cited claim values."
        ),
        "mode": mode,
        "dataset": dataset,
        "questions": len(results),
        "old_meets_expectation": old,
        "meets_expectation": new,
        "claim_backed_meets_expectation": backed,
        "delta": old - new,
        "by_answerable": {
            "answerable": {
                "questions": len(answerable),
                "old": sum(int(item["score"]["old_meets_expectation"]) for item in answerable),
                "new": sum(int(item["score"]["meets_expectation"]) for item in answerable),
            },
            "unsupported": {
                "questions": len(unsupported),
                "old": sum(int(item["score"]["old_meets_expectation"]) for item in unsupported),
                "new": sum(int(item["score"]["meets_expectation"]) for item in unsupported),
            },
        },
        "survived": [
            item["score"]["id"]
            for item in results
            if item["score"]["old_meets_expectation"] and item["score"]["meets_expectation"]
        ],
        "lost": [
            {
                "id": item["score"]["id"],
                "category": item["score"]["category"],
                "failures": item["score"]["failures"],
                "reason": loss_reason(item["score"]["failures"]),
                "answer": item.get("answer", ""),
            }
            for item in results
            if item["score"]["old_meets_expectation"] and not item["score"]["meets_expectation"]
        ],
        "gained": [
            {"id": item["score"]["id"], "failures": item["score"]["failures"]}
            for item in results
            if not item["score"]["old_meets_expectation"] and item["score"]["meets_expectation"]
        ],
        "failure_counts": dict(failures.most_common()),
        "by_category": dict(sorted(by_category.items())),
    }


def loss_reason(failures: list[str]) -> str:
    names = {failure.split(":")[0] for failure in failures}
    if "clarification" in names:
        return "skipped_work_clarification"
    if "declined" in names:
        return "declined_answerable"
    if "unbacked_numbers" in names:
        return "unbacked_number"
    if "unbacked_entities" in names:
        return "wrong_subject"
    if "required_facts" in names or "required_entities" in names or "required_phrases" in names:
        return "missing_required_fact"
    if "missing_turning_detail" in names:
        return "missing_turning_detail"
    if "not_substantive" in names:
        return "not_substantive"
    return "other"


def print_table(summary: dict) -> None:
    print(f"mode={summary['mode']} dataset={summary['dataset']} questions={summary['questions']}")
    print("| Category | Questions | Old | New | Claim-backed |")
    print("| --- | --- | --- | --- | --- |")
    for category, row in summary["by_category"].items():
        print(
            f"| {category} | {row['questions']} | {row['old']} | {row['new']} | "
            f"{row['claim_backed']} |"
        )
    print(
        f"| Total | {summary['questions']} | {summary['old_meets_expectation']} | "
        f"{summary['meets_expectation']} | {summary['claim_backed_meets_expectation']} |"
    )


async def build_archive():
    return await build_archive_values()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--questions", type=Path, default=None)
    parser.add_argument("--heldout", action="store_true", help="use the held-out question set")
    parser.add_argument(
        "--responses", type=Path, help="offline mode: re-score this responses JSONL"
    )
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--all", action="store_true", help="run every question in the set")
    parser.add_argument("--limit", type=int, default=0, help="cap live questions")
    parser.add_argument("--ids", default="", help="comma-separated case ids to run")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    questions = args.questions or (HELDOUT if args.heldout else QUESTIONS)
    cases = load_cases(questions)
    archive = asyncio.run(build_archive())
    if args.responses:
        results = run_offline(cases, args.responses, archive)
        mode = "offline"
    else:
        picked = sample(cases, args.per_category, args.all)
        if args.ids:
            wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
            picked = [case for case in picked if case["id"] in wanted]
        if args.limit:
            picked = picked[: args.limit]
        results = asyncio.run(run_live(picked, archive, args.timeout))
        mode = "live"
    summary = summarize(mode, str(questions), results)
    summary["source"] = str(args.responses) if args.responses else "live in-process API"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    scored = args.out.with_suffix(".scored.jsonl")
    scored.write_text(
        "".join(json.dumps(item["score"]) + "\n" for item in results),
        encoding="utf-8",
    )
    if mode == "live":
        raw = args.out.with_suffix(".responses.jsonl")
        raw.write_text(
            "".join(
                json.dumps({key: value for key, value in item.items() if key != "score"}) + "\n"
                for item in results
            ),
            encoding="utf-8",
        )
    print_table(summary)
    print(f"report: {args.out}")
    print(f"scored: {scored}")


if __name__ == "__main__":
    main()
