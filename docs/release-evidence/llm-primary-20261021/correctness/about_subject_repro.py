"""'What about <phrase>?' must ask which subject only when the phrase names an unknown one.

Runs the real prepare() path against the local DB after a prior record turn. No model calls.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/about_subject_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

# (follow-up, must ask which subject); every case follows a team record turn, and the
# period cases also follow a team points turn below.
CASES = [
    ("What about the second quarter?", False),
    ("What about the second half?", False),
    ("What about Q4?", False),
    ("What about the 3rd quarter?", False),
    ("What about Nobody McFake in the second quarter?", True),
    ("What about at home?", False),
    ("What about on the road?", False),
    ("What about in March?", False),
    ("What about the last 5 games?", False),
    ("What about the Celtics?", False),
    ("What about Brunson's assists?", False),
    ("What about their points?", False),
    ("What about Nobody McFake?", True),
    ("What about Nobody McFake's points?", True),
    ("What about nobody mcfake at home?", True),
    ("What about Zorblax in the playoffs?", True),
]


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        priors = ("What was their record?", "How many points did they score per game?")
        for prior, (question, want_ask) in ((p, c) for p in priors for c in CASES):
            first = AnalystTools(db, release, prior, "2025-26", {})
            await first.prepare()
            tools = AnalystTools(db, release, question, "2025-26", first.state)
            await tools.prepare()
            assert tools.scope is not None
            asked = tools.scope.requires_clarification
            ok = asked == want_ask
            bad += not ok
            print(
                "OK " if ok else "BAD",
                f"after {prior!r}: {question!r} asks={asked} (want {want_ask})",
            )
    print("FAILURES", bad)


asyncio.run(main())
