"""When the model fails on an elliptical follow-up, the factual fallback must still answer it.

Every provider call raises, so the turn always falls back. The fallback has to pick the
previous topic's facts in the follow-up's scope. No model calls. Needs a disposable Redis db.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/13 \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/followup_fallback_repro.py
"""

import asyncio

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services import analyst_provider
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

REGULAR = {"season_type": "regular", "all_phases": False}
ALL = {"season_type": None, "all_phases": True}
CASES = [
    ("What was their regular-season record?", REGULAR, "And overall?", "wins: 69 over 101"),
    ("What was their regular-season record?", ALL, "And in the playoffs?", "wins: 16 over 19"),
    ("What was their regular-season record?", REGULAR, "And at home?", "wins: 30 over 40"),
]


class Failing:
    last_metadata: dict = {}

    async def generate(self, **kwargs):
        raise RuntimeError("provider unavailable")


async def main() -> None:
    analyst_provider.get_llm_adapter = lambda: Failing()  # type: ignore[assignment]
    bad = 0
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        for intent, scope, question, want in CASES:
            state = {"intent": intent, "scope": scope, "release": release.version}
            tools = AnalystTools(db, release, question, "2025-26", state)
            await tools.prepare()
            result = await AnalystLoop(tools, []).run()
            answer = result["answer"]
            ok = want in answer and not result["llm_validated"]
            bad += not ok
            print("OK " if ok else "BAD", f"{question!r} -> {answer[:160]!r} (want {want!r})")
    print("FAILURES", bad)


asyncio.run(main())
