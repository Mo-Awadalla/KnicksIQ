"""Follow-up tool calls must run in the follow-up's scope, not the topic's or the model's.

Each case prepares a follow-up turn after a prior turn, then executes a tool call and counts
the games behind the returned record claim. No model calls. Local release: 82 regular season,
19 playoffs, 101 games in all.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/followup_dispatch_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from sqlalchemy import select

REGULAR = {"season_type": "regular", "all_phases": False}
# (label, prior intent, prior scope, follow-up, model call question or None for prefetch, games)
CASES = [
    (
        "prefetch, implicit topic",
        "What was the Knicks' record?",
        REGULAR,
        "And overall?",
        None,
        101,
    ),
    (
        "prefetch, explicit topic",
        "What was their regular-season record?",
        REGULAR,
        "And overall?",
        None,
        101,
    ),
    (
        "prefetch, playoffs",
        "What was their regular-season record?",
        REGULAR,
        "And in the playoffs?",
        None,
        19,
    ),
    (
        "model names old phase",
        "What was their record?",
        REGULAR,
        "And overall?",
        "Knicks regular-season record",
        101,
    ),
    (
        "model names other phase",
        "What was their record?",
        REGULAR,
        "And in the playoffs?",
        "Knicks regular season record",
        19,
    ),
    ("model plain", "What was their record?", REGULAR, "And overall?", "Knicks record", 101),
]


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        for label, intent, scope, question, call_question, want in CASES:
            state = {"intent": intent, "scope": scope, "release": release.version}
            tools = AnalystTools(db, release, question, "2025-26", state)
            await tools.prepare()
            if call_question is None:
                calls = prefetch_calls(tools)
            else:
                calls = [
                    ToolCall(name="get_team_stats", question=call_question, aggregation="total")
                ]
            if not calls:
                print("BAD", label, "no prefetch")
                bad += 1
                continue
            result = await tools.execute(calls[0])
            wins = next((c for c in result.claims if c.metric_id == "wins"), None)
            games = len(wins.game_ids or []) if wins else None
            ok = games == want
            bad += not ok
            print("OK " if ok else "BAD", f"{label}: {question!r} -> {games} games (want {want})")
    print("FAILURES", bad)


asyncio.run(main())
