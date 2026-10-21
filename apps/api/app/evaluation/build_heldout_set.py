"""Build the 60-question held-out analyst evaluation set from the active release.

Facts are computed from the local database by this script. No model labels, no hand-entered
numbers. The set is paraphrased away from questions.jsonl and the games and players differ.

    DB_URL=postgresql+asyncpg://... uv run --package knicksiq-api \
        python -m app.evaluation.build_heldout_set
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path

import asyncpg

from app.evaluation.heldout_cases import (
    ALIASES,
    CASES,
    UNSUPPORTED,
    Case,
    _narrative_cases,
    _turning_cases,
)
from app.evaluation.heldout_facts import Archive, dsn, load_archive

HERE = Path(__file__).resolve().parent
TARGET = HERE / "heldout_questions.jsonl"
META = HERE / "heldout_questions.meta.json"
COMPUTED_FROM = "2025-26.20260928.1"
POLICY = (
    "Held-out set. Do not tune prompts, tools, thresholds or labels against individual items. "
    "The only permitted use is the aggregate scorer report and its per-question check output."
)


def build(archive: Archive) -> list[dict]:
    cases: list[Case] = CASES + _narrative_cases() + _turning_cases()
    for question, facts, filters in ALIASES:
        cases.append(Case("aliases_typos", question, "retrieval_rag", True, facts, filters))
    for question in UNSUPPORTED:
        cases.append(Case("unsupported", question, None, False, lambda a: ([], [], []), {}))
    rows = []
    counts: defaultdict[str, int] = defaultdict(int)
    for case in cases:
        counts[case.category] += 1
        facts, entities, phrases = case.facts(archive)
        if case.answerable:
            if not facts:
                raise RuntimeError(f"missing required facts: {case.question}")
            if not entities:
                raise RuntimeError(f"missing required entities: {case.question}")
        elif facts or entities:
            raise RuntimeError(f"unsupported case carries facts: {case.question}")
        row = {
            "id": f"heldout-{case.category}-{counts[case.category]:03d}",
            "category": case.category,
            "question": case.question,
            "expected_route": case.route,
            "answerable": case.answerable,
            "required_facts": facts,
            "required_entities": entities,
            "filters": case.filters,
            "label_status": "heldout",
        }
        phrases = list(case.required_phrases or phrases)
        if phrases:
            row["required_phrases"] = phrases
        rows.append(row)
    if len(rows) != 60:
        raise RuntimeError(f"expected 60 cases, got {len(rows)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=TARGET)
    args = parser.parse_args()

    async def run() -> list[dict]:
        connection = await asyncpg.connect(dsn())
        try:
            return build(await load_archive(connection))
        finally:
            await connection.close()

    rows = asyncio.run(run())
    args.out.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["category"]] += 1
    META.write_text(
        json.dumps(
            {
                "split": "heldout",
                "count": len(rows),
                "categories": dict(sorted(counts.items())),
                "generated_by": "app/evaluation/build_heldout_set.py",
                "computed_from": COMPUTED_FROM,
                "label_source": "database",
                "tuning_policy": POLICY,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} held-out cases to {args.out}")
    for category, count in sorted(counts.items()):
        print(f"  {category}: {count}")


if __name__ == "__main__":
    main()
