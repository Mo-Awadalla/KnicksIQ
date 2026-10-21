#!/usr/bin/env python3
"""Run every quarter/half/overtime question from questions.jsonl through the live analyst.

The main harness samples by category; this seam keeps its HTTP path and scorer but selects
questions by content so the whole period subset is measured, not the first N rows per category.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import analyst_live_e2e as harness  # noqa: E402

PERIOD = re.compile(r"\b(quarter|half|halftime|4th|fourth|overtime|ot)\b", re.I)


def period_rows() -> list[dict]:
    rows = [json.loads(line) for line in harness.QUESTIONS.read_text().splitlines()]
    return [row for row in rows if PERIOD.search(row["question"])]


async def run(trials: int, cases: list[dict]) -> list[dict]:
    archive = await harness.build_archive()
    results: list[dict] = []
    for trial in range(1, trials + 1):
        for item in await harness.run_live(cases, archive, 60):
            results.append({"trial": trial, **item})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    cases = period_rows()
    questions = args.out.with_name("period-questions.jsonl")
    questions.write_text("".join(json.dumps(case) + "\n" for case in cases))
    results = asyncio.run(run(args.trials, cases))
    args.out.write_text("".join(json.dumps(item) + "\n" for item in results))
    summary = {
        "questions": len(cases),
        "trials": args.trials,
        "responses": len(results),
        "per_question": {
            qid: [
                {
                    "trial": item["trial"],
                    "outcome": item["outcome"],
                    "refused": item["refused"],
                    "score": item["score"]["meets_expectation"],
                    "failures": item["score"]["failures"],
                    "answer": item["answer"],
                    "tool_calls": item["tool_calls"],
                }
                for item in results
                if item["id"] == qid
            ]
            for qid in dict.fromkeys(item["id"] for item in results)
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
