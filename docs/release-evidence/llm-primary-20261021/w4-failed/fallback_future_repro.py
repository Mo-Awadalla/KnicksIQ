#!/usr/bin/env python3
"""Forced-provider-failure fallback check for future questions and benign 'will' requests.

Every provider call raises, so each turn ends in the factual fallback. The future case
must decline (no archive facts) and the benign archive requests must keep answering with
facts. Offline: no provider traffic.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/7 \
    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-failed/fallback_future_repro.py \
      --out /tmp/fallback-future.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import app.services.analyst_provider as provider_module
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

DECLINE = re.compile(
    r"\b(i can(?:'|’)?t|i cannot|can(?:'|’)?t (?:give|provide|answer|predict|verify)|"
    r"cannot (?:give|provide|answer|predict)|not able to|unable to|do(?:es)? not (?:include|"
    r"cover|contain)|doesn(?:'|’)?t (?:include|cover|contain)|no (?:live|future|current))",
    re.I,
)
FUTURE = {
    "unsupported-008": "How will Brunson play next season?",
    "future-next-year": "How will the Knicks do next year?",
    "future-tomorrow": "Who will win tomorrow's game?",
}
BENIGN = {
    "benign-001": "Will you tell me Brunson's points per game this season?",
    "benign-002": "Will you show me the Knicks' record for the 2025-26 season?",
    "benign-003": "Which player will I see leading the team in assists?",
    "benign-004": "Who will I see at the top of the rebounding list?",
    "benign-005": "Will you compare Brunson's home and road scoring?",
    "benign-006": "Will you pull up the scoring from their final game?",
    "benign-007": "How many points will I find for Brunson in their final game?",
    "benign-008": "Which quarter will I see the biggest Knicks run in?",
    "benign-009": "Will you explain why the Knicks lost to Boston?",
    "benign-010": "What will I see if I look at their three-point shooting at home?",
}


class Failing:
    last_metadata: dict[str, Any] = {}

    async def generate(self, **_: Any) -> str:
        raise RuntimeError("provider unavailable")


async def turn(db: Any, release: Any, question: str) -> dict[str, Any]:
    state = {"intent": question, "scope": {}, "release": release.version}
    tools = AnalystTools(db, release, question, "2025-26", state)
    await tools.prepare()
    result = await AnalystLoop(tools, []).run()
    answer = result["answer"]
    return {
        "question": question,
        "answer": answer,
        "claims": len(result["citations"]),
        "refused": result["refused"],
        "llm_validated": result["llm_validated"],
        "declined": bool(DECLINE.search(answer)),
        "route": result["route"],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    provider_module.get_llm_adapter = lambda **_: Failing()  # type: ignore[assignment]
    rows: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        release = (await db.execute(select(DatasetRelease).limit(1))).scalar_one()
        for case_id, question in FUTURE.items():
            row = await turn(db, release, question)
            row.update(case_id=case_id, kind="future")
            row["future_scope"] = "future games or seasons" in row["answer"]
            row["ok"] = row["declined"] and row["claims"] == 0 and row["future_scope"]
            rows.append(row)
            print("OK " if row["ok"] else "BAD", case_id, repr(row["answer"][:120]))
        for case_id, question in BENIGN.items():
            row = await turn(db, release, question)
            row.update(case_id=case_id, kind="benign")
            # The detector must not divert a "will you/will I" archive request. Where the
            # fallback can already answer (claims > 0) it must keep doing so; the leader
            # and period requests keep their pre-existing generic decline.
            row["future_scope"] = "future games or seasons" in row["answer"]
            row["ok"] = not row["future_scope"] and (
                row["claims"] > 0 or "verified archive facts are unavailable" in row["answer"]
            )
            rows.append(row)
            print("OK " if row["ok"] else "BAD", case_id, repr(row["answer"][:120]))
    summary = {
        "future_failures": sum(1 for row in rows if row["kind"] == "future" and not row["ok"]),
        "benign_failures": sum(1 for row in rows if row["kind"] == "benign" and not row["ok"]),
        "rows": rows,
    }
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


asyncio.run(main())
