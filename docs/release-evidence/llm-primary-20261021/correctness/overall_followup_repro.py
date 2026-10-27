"""A follow-up that names all phases must not inherit the previous turn's phase.

Checks the resolved phase and the size of the selected game population, which is what the
tools compute over. Local release: 82 regular season, 101 all phases, 49 home games overall.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/overall_followup_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

REGULAR = {"season_type": "regular"}
ALL = {"season_type": None, "all_phases": True}
CASES = [
    ("What was their record?", {}, "regular", 82),
    ("And overall?", REGULAR, None, 101),
    ("And including playoffs?", REGULAR, None, 101),
    ("And in the playoffs?", REGULAR, "playoffs", 19),
    ("And at home?", ALL, None, 49),
    ("And at home?", REGULAR, "regular", None),
]


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        for question, prior, want_type, want_games in CASES:
            tools = AnalystTools(db, release, question, "2025-26", {"scope": prior})
            await tools.prepare()
            assert tools.scope is not None
            games = len(tools.selected_games(tools.scope))
            ok = tools.scope.season_type == want_type and want_games in (None, games)
            bad += not ok
            print(
                "OK " if ok else "BAD",
                f"{question!r} after {prior} -> {tools.scope.season_type}, {games} games",
                f"(want {want_type}, {want_games})",
            )
    print("FAILURES", bad)


asyncio.run(main())
