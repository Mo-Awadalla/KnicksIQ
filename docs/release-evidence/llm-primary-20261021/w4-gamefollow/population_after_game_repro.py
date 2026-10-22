"""After a single-game turn, a question that needs many games must not be scoped to one.

An average or a "best game" over one game is meaningless, so it must not stay on the prior
game (a superlative may still resolve to the one extreme game, which is a different game);
a stat about the game itself keeps the game. Runs prepare() against the local DB.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-gamefollow/population_after_game_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

PRIOR = "How did the Knicks do against the Hawks on January 2?"
# (follow-up, stays on the prior game)
CASES = [
    ("What was the margin?", True),
    ("Who scored the most?", True),
    ("How many points did Brunson have in that game?", True),
    ("How many threes did they make?", True),
    ("How many points did Brunson average?", False),
    ("What was their best scoring game?", False),
    ("What was their biggest win?", False),
    ("How many rebounds per game did Towns get?", False),
]


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        first = AnalystTools(db, release, PRIOR, "2025-26", {"release": release.version})
        await first.prepare()
        assert first.scope is not None
        prior = {g.id for g in first.selected_games(first.scope)}
        assert len(prior) == 1, prior
        for question, want_prior in CASES:
            tools = AnalystTools(db, release, question, "2025-26", dict(first.state))
            await tools.prepare()
            assert tools.scope is not None
            games = {g.id for g in tools.selected_games(tools.scope)}
            ok = (games == prior) == want_prior
            bad += not ok
            print(
                "OK " if ok else "BAD",
                f"{question!r}: {len(games)} games, prior game={games == prior} (want {want_prior})",
            )
    print("FAILURES", bad)


asyncio.run(main())
