#!/usr/bin/env python3
"""Offline reproduction for the decline causes in the final 70-question trials.

Failure modes written before the fix (each check is one):
1. A split question (home/road, two opponents, wins/losses, first N, All-Star break)
   is prefetched to get_team_stats or to no tool, so the split tool never runs.
2. A game-flow question (run, deficit, comeback, collapse, lost lead, possessions) is
   prefetched to discover_facts, so get_game_flow runs late or returns ambiguous.
3. A quarter/halftime question is prefetched to get_team_stats, so get_period_scoring
   returns an entity ambiguity instead of the period report.
4. Split, flow and period claims are absent from the fallback family list, so a
   reviewer rejection replaces a correct answer with "I can't answer".
5. Routing ignores the requested metric and sends turnover, shooting or bench
   questions to a tool that only has scores, producing an unrelated answer.
6. Single-population prefetch (season record, last N window, what happened vs a team)
   regresses when the split routes are added.
7. The prompt and tool descriptions do not name the split/flow/period routes, do not
   allow quoting a tool-computed extreme, and do not forbid unbacked specifics in a
   decline.

Run against the local restored release (never the repo .env DB_URL):

  DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  REDIS_URL=redis://localhost:56500/3 \
  uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w3-declines/reproduce_declines.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_fallback import fallback_claims
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_provider import orchestrator_system_prompt
from app.services.analyst_tool_registry import tools_hint
from app.services.analyst_tools import AnalystTools

QUESTIONS = Path("apps/api/app/evaluation/questions.jsonl")

# id -> (tool that must lead prefetch, substrings that must appear in the tool claims)
ROUTES: dict[str, tuple[str, list[str]]] = {
    "date_range_last_n-005": ("get_team_splits", ["18-9 in 27 games"]),
    "date_range_last_n-010": ("get_team_splits", ["7-3 in 10 games"]),
    "comparisons-001": ("get_team_splits", ["119.00 for", "114.02 for"]),
    "comparisons-003": ("get_team_splits", ["3-1 in 4 games", "5-0 in 5 games"]),
    "comparisons-004": ("get_team_splits", ["first 10 games", "6-4 in 10 games"]),
    "comparisons-009": ("get_period_scoring", ["Q3", "Q4"]),
    "single_game_narrative-001": ("get_game_flow", ["largest lead lost", "14 points"]),
    "single_game_narrative-003": ("get_period_scoring", ["Q4 30-28", "Q4 15-28"]),
    "single_game_narrative-005": ("get_period_scoring", ["half 53-47", "half 72-47"]),
    "single_game_narrative-008": ("get_game_flow", ["13-0 run"]),
    "aliases_typos-005": ("get_game_flow", ["20-0 run"]),
    "aliases_typos-007": ("get_period_scoring", ["Q4 23-27"]),
    "aliases_typos-010": ("get_game_flow", ["19 points"]),
    "turning_points-001": ("get_game_flow", ["17-0 run"]),
    "turning_points-003": ("get_game_flow", ["largest lead lost", "14 points"]),
    "turning_points-005": ("get_game_flow", ["21 points"]),
    "turning_points-007": ("get_game_flow", ["15-0 run"]),
    "turning_points-008": ("get_game_flow", ["21 points"]),
    "turning_points-009": ("get_game_flow", ["12 points"]),
}

# ids that must keep their previous single-population behavior.
UNCHANGED: dict[str, str | None] = {
    "exact_statistics-001": "get_team_stats",
    "date_range_last_n-001": "get_team_stats",
    "date_range_last_n-007": "get_team_stats",
    "aliases_typos-002": "get_team_stats",
    "unsupported-001": None,
    "unsupported-009": None,
}

# ids whose metric no score-based tool covers; a split route would answer the wrong question.
NOT_SPLIT = (
    "comparisons-005",
    "comparisons-006",
    "comparisons-010",
    "aliases_typos-008",
)

PROMPT_PHRASES = (
    "get_team_splits",
    "observed maximum",
    "list the matching archived games",
    "must not add specific numbers",
)


def claim_texts(claims) -> str:
    parts = []
    for claim in claims:
        parts.append(claim.statement)
        if claim.metric_id == "period_report":
            parts.append(str(claim.value))
    return "\n".join(parts)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_suffix(".json"))
    args = parser.parse_args()
    cases = {
        row["id"]: row
        for row in (json.loads(line) for line in QUESTIONS.read_text().splitlines() if line)
        if row["category"] != "follow_ups"
    }
    results: list[dict] = []

    def record(check: str, item: str, expected: object, actual: object) -> None:
        passed = expected == actual if not isinstance(expected, list) else all(
            part in str(actual) for part in expected
        )
        results.append(
            {"check": check, "id": item, "expected": expected, "actual": actual, "pass": passed}
        )

    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        for question_id, (tool, facts) in ROUTES.items():
            case = cases[question_id]
            tools = AnalystTools(db, release, case["question"], release.season, {})
            await tools.prepare()
            calls = prefetch_calls(tools)
            record("route", question_id, tool, calls[0].name if calls else None)
            executed = [await tools.execute(call) for call in calls]
            record("facts", question_id, facts, claim_texts([c for r in executed for c in r.claims]))

            loop = AnalystLoop(tools, [])
            loop.results = executed
            assert fallback_claims(loop) or True  # exercised below through the rendered text
            answer = loop.render_fallback("Proposed wording did not pass evidence review.")
            record("fallback", question_id, facts, answer["answer"])

        for question_id, expected in UNCHANGED.items():
            tools = AnalystTools(db, release, cases[question_id]["question"], release.season, {})
            await tools.prepare()
            calls = prefetch_calls(tools)
            record("unchanged", question_id, expected, calls[0].name if calls else None)

        for question_id in NOT_SPLIT:
            tools = AnalystTools(db, release, cases[question_id]["question"], release.season, {})
            await tools.prepare()
            calls = prefetch_calls(tools)
            names = {call.name for call in calls}
            record(
                "metric-gate",
                question_id,
                False,
                bool(names & {"get_team_splits"}),
            )

    prompt = orchestrator_system_prompt() + "\n" + tools_hint()
    for phrase in PROMPT_PHRASES:
        record("prompt", phrase, True, phrase.lower() in prompt.lower())

    failed = [row for row in results if not row["pass"]]
    args.out.write_text(json.dumps({"checks": results, "failed": len(failed)}, indent=2) + "\n")
    for row in results:
        print(f"{'PASS' if row['pass'] else 'FAIL'} {row['check']:<12} {row['id']}")
        if not row["pass"]:
            print(f"     expected {row['expected']!r}")
            print(f"     actual   {str(row['actual'])[:300]!r}")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; artifact {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
