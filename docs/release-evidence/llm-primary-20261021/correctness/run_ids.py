#!/usr/bin/env python3
"""Run chosen question ids or categories through the in-process llm_primary path.

Same application path as tools/release/analyst_live_e2e.py, but targeted at the ids under
audit and able to repeat each question for reviewer stochasticity.

    DB_URL=... REDIS_URL=redis://localhost:56500/13 ANALYSIS_ANSWER_MODE=llm_primary \
    AI_API_KEY=... OPENROUTER_MONTHLY_CUTOFF_USD=2 \
    uv run --package knicsiq-api python run_ids.py --ids a,b --trials 2 --out result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from collections import Counter
from pathlib import Path

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE.parents[3] / "apps/api/app/evaluation/questions.jsonl"
sys.path.insert(0, str(HERE.parents[3] / "tools/release"))
from analyst_live_e2e import FailureCapture, classify, meets_expectation  # noqa: E402


def load(ids: list[str], categories: list[str]) -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    if categories:
        return [row for row in rows if row["category"] in categories]
    wanted = set(ids)
    return [row for row in rows if row["id"] in wanted]


async def run(rows: list[dict], trials: int) -> list[dict]:
    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    app = create_app()
    results = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            for trial in range(1, trials + 1):
                for row in rows:
                    capture.records.clear()
                    response = await client.post(
                        "/analysis/query",
                        json={
                            "question": row["question"],
                            "season": "2025-26",
                            "turn_id": "correctness-" + uuid.uuid4().hex,
                            "expected_revision": 0,
                        },
                    )
                    body = response.json() if response.status_code == 200 else {}
                    outcome = (
                        classify(body, capture.records) if body else f"http_{response.status_code}"
                    )
                    results.append(
                        {
                            "id": row["id"],
                            "category": row["category"],
                            "answerable": row["answerable"],
                            "question": row["question"],
                            "trial": trial,
                            "outcome": outcome,
                            "meets_expectation": meets_expectation(row, outcome),
                            "answer": body.get("answer") or "",
                            "warnings": body.get("warnings") or [],
                            "citations": len(body.get("citations") or []),
                            "degraded": body.get("degraded"),
                            "llm_validated": body.get("llm_validated"),
                        }
                    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="")
    parser.add_argument("--categories", default="")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = load([i for i in args.ids.split(",") if i], [c for c in args.categories.split(",") if c])
    if not rows:
        raise SystemExit("No matching questions")
    results = asyncio.run(run(rows, args.trials))
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    responses = args.out.with_suffix(".responses.jsonl")
    responses.write_text("".join(json.dumps(item) + "\n" for item in results))
    outcomes = Counter(item["outcome"] for item in results)
    print(json.dumps({"questions": len(rows), "answers": len(results), "outcomes": outcomes}, indent=2))


if __name__ == "__main__":
    main()
