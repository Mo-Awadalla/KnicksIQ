"""A follow-up must keep the direction of a first-N window, not only its size.

Turn 1 asks about the first 10 games; turn 2 changes only the site or metric. Each case checks
the resolved game set against SQL-free expectations taken from the release's own game order.
No model calls.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/first_n_followup_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from sqlalchemy import select


async def turn(db, release, question: str, state: dict) -> AnalystTools:
    tools = AnalystTools(db, release, question, "2025-26", state)
    await tools.prepare()
    return tools


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        probe = await turn(db, release, "What was their record?", {})
        # A game-count window spans every phase (season-phase policy), so "last 10 games"
        # reaches into the playoffs.
        ordered = sorted(probe.games, key=lambda g: g.game_date)
        cases = [
            ("What was their record in the first 10 games?", None, ordered[:10]),
            ("What was their record in their last 10 games?", None, ordered[-10:]),
            ("What was their record in the first 10 games?", "And their points?", ordered[:10]),
            ("What was their record in the first 10 games?", "What about at home?",
             [g for g in ordered if g.home_team_id == "NYK"][:10]),
            ("What was their record in their last 10 games?", "And their points?", ordered[-10:]),
        ]  # fmt: skip
        for first, follow, want in cases:
            state: dict = {"release": release.version}
            tools = await turn(db, release, first, state)
            if follow is not None:
                tools = await turn(db, release, follow, tools.state)
            assert tools.scope is not None
            got = {g.id for g in tools.selected_games(tools.scope)}
            # The team tool is what answers; its claims must cover the same games.
            result = await tools.execute(
                ToolCall(name="get_team_stats", question=tools.question, aggregation="total")
            )
            wins = next((c for c in result.claims if c.metric_id == "wins"), None)
            claimed = set(wins.game_ids or []) if wins else set()
            ok = got == {g.id for g in want} and claimed == got
            bad += not ok
            label = f"{first!r}" + (f" -> {follow!r}" if follow else "")
            dates = sorted(g.game_date.isoformat() for g in tools.selected_games(tools.scope))
            print("OK " if ok else "BAD", label, f"{len(got)} games", dates[:1], dates[-1:])
    print("FAILURES", bad)


asyncio.run(main())
