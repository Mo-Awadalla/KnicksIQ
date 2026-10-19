"""End-to-end check of the llm_primary analyst against a real provider and a restored release.

Runs candidate questions through the in-process FastAPI app (same code path as production) and
records, per question, whether the model's answer was validated or fell back, and why.
Needs a loaded and activated release (DB_URL), Redis with the monthly ledger (REDIS_URL), and
the provider settings (AI_*, ANALYSIS_ANSWER_MODE=llm_primary). Never contacts Qdrant.

    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import re
import uuid
from pathlib import Path

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"


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


def sample(per_category: int) -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
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


def meets_expectation(row: dict, outcome: str) -> bool:
    """Answerable questions need a substantive validated answer; unsupported ones a decline."""
    if row["answerable"]:
        return outcome == "validated"
    return outcome == "validated_declined"


async def run(per_category: int) -> dict:
    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    app = create_app()
    results = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            for row in sample(per_category):
                capture.records.clear()
                response = await client.post(
                    "/analysis/query",
                    json={
                        "question": row["question"],
                        "season": "2025-26",
                        "turn_id": "e2e-" + uuid.uuid4().hex,
                        "expected_revision": 0,
                    },
                )
                body = response.json() if response.status_code == 200 else {}
                outcome = (
                    classify(body, capture.records)
                    if body
                    else f"http_{response.status_code}"
                )
                results.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "answerable": row["answerable"],
                        "question": row["question"],
                        "outcome": outcome,
                        "meets_expectation": meets_expectation(row, outcome),
                        "answer": body.get("answer") or "",
                        "citations": len(body.get("citations") or []),
                        "warnings": body.get("warnings") or [],
                    }
                )
    by_outcome = collections.Counter(item["outcome"] for item in results)
    by_category: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for item in results:
        by_category[item["category"]]["meets_expectation"] += item["meets_expectation"]
        by_category[item["category"]]["questions"] += 1
    met = sum(item["meets_expectation"] for item in results)
    return {
        "scope": "llm_validated is reviewer acceptance. meets_expectation also requires a "
        "substantive answer for answerable questions and a decline for unsupported ones. "
        "Expectations come from unreviewed draft labels.",
        "questions": len(results),
        "meets_expectation": met,
        "meets_expectation_rate": round(met / len(results), 3),
        "outcomes": dict(by_outcome),
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(run(args.per_category))
    results = report.pop("results")
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    responses = args.out.with_suffix(".responses.jsonl")
    responses.write_text("".join(json.dumps(item) + "\n" for item in results))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
