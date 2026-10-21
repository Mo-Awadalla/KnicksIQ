#!/usr/bin/env python3
"""Run every quarter/half/overtime question from questions.jsonl through the live analyst.

The main harness samples by category; this seam keeps its HTTP path and result schema but
selects questions by content so the whole period subset is measured, not the first N rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import analyst_live_e2e as harness  # noqa: E402

PERIOD = re.compile(r"\b(quarter|half|halftime|4th|fourth|overtime|ot)\b", re.I)


def period_rows() -> list[dict]:
    rows = [json.loads(line) for line in harness.QUESTIONS.read_text().splitlines()]
    return [row for row in rows if PERIOD.search(row["question"])]


async def run(trials: int) -> list[dict]:
    rows = period_rows()
    results: list[dict] = []
    for trial in range(1, trials + 1):
        harness.sample = lambda _n: rows  # type: ignore[assignment]
        report = await harness.run(len(rows))
        for item in report["results"]:
            results.append({"trial": trial, **item})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    results = asyncio.run(run(args.trials))
    args.out.write_text("".join(json.dumps(item) + "\n" for item in results))
    summary = {
        "questions": len({item["id"] for item in results}),
        "trials": args.trials,
        "responses": len(results),
        "per_question": {
            qid: [
                {"trial": i["trial"], "outcome": i["outcome"], "answer": i["answer"]}
                for i in results
                if i["id"] == qid
            ]
            for qid in dict.fromkeys(i["id"] for i in results)
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
