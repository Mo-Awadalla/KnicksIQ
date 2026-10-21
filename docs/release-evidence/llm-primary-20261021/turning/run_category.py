"""Run one question category through the in-process analyst with N trials.

This is a thin filter over the release harness: it reuses the harness's failure
capture, outcome classifier and expectation rule, but samples every question in one
category and repeats each question ``--trials`` times.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/turning/run_category.py \
      --category turning_points --trials 2 --out base.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import importlib.util
import json
import logging
import os
import uuid
from pathlib import Path

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
HARNESS = ROOT / "tools/release/analyst_live_e2e.py"


def _harness():
    spec = importlib.util.spec_from_file_location("analyst_live_e2e", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(category: str, ids: set[str]) -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    return [
        row
        for row in rows
        if row["category"] == category and (not ids or row["id"] in ids)
    ]


async def run(category: str, trials: int, ids: set[str]) -> dict:
    harness = _harness()
    capture = harness.FailureCapture()
    logging.getLogger().addHandler(capture)
    app = create_app()
    results: list[dict] = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            for trial in range(1, trials + 1):
                for row in _load(category, ids):
                    capture.records.clear()
                    response = await client.post(
                        "/analysis/query",
                        json={
                            "question": row["question"],
                            "season": "2025-26",
                            "turn_id": f"turning-{uuid.uuid4().hex}",
                            "expected_revision": 0,
                        },
                    )
                    body = response.json() if response.status_code == 200 else {}
                    outcome = (
                        harness.classify(body, capture.records)
                        if body
                        else f"http_{response.status_code}"
                    )
                    results.append(
                        {
                            "trial": trial,
                            "id": row["id"],
                            "category": row["category"],
                            "answerable": row["answerable"],
                            "question": row["question"],
                            "outcome": outcome,
                            "meets_expectation": harness.meets_expectation(row, outcome),
                            "answer": body.get("answer") or "",
                            "citations": len(body.get("citations") or []),
                            "warnings": body.get("warnings") or [],
                        }
                    )
    by_id: dict[str, list[dict]] = collections.defaultdict(list)
    for item in results:
        by_id[item["id"]].append(item)
    summary = {
        "category": category,
        "trials": trials,
        "questions": len(by_id),
        "responses": len(results),
        "meets_expectation": sum(item["meets_expectation"] for item in results),
        "meets_all_trials": sum(all(r["meets_expectation"] for r in rows) for rows in by_id.values()),
        "outcomes": dict(collections.Counter(item["outcome"] for item in results)),
        "by_question": {
            key: {
                "meets": sum(item["meets_expectation"] for item in rows),
                "outcomes": [item["outcome"] for item in rows],
                "answers": [item["answer"] for item in rows],
            }
            for key, rows in by_id.items()
        },
        "results": results,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", required=True)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--ids", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ids = {item.strip() for item in args.ids.split(",") if item.strip()}
    summary = asyncio.run(run(args.category, args.trials, ids))
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    responses = args.out.with_suffix(".responses.jsonl")
    responses.write_text("".join(json.dumps(item) + "\n" for item in summary["results"]))
    report = {key: value for key, value in summary.items() if key != "results"}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
