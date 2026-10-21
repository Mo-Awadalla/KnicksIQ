#!/usr/bin/env python3
"""Deterministic reproduction of the correctness defects, without the model provider.

Runs the in-process AnalystTools/query resolution and the no-model fallback for the audited
question ids. The output is committed next to this script as repro-before.json.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
        uv run --package knicksiq-api python repro.py > repro-before.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from sqlalchemy import select

CASES = [
    # id, question, tool the model would need
    ("date_range_last_n-006", "How many road games did they win in December?", "get_team_stats"),
    ("exact_statistics-008", "How many wins did they have in December?", "get_team_stats"),
    ("aliases_typos-004", "Tell me about KAT vs the Raps.", "get_player_stats"),
    ("aliases_typos-006", "How did they do v ATL?", "get_team_stats"),
    ("aliases_typos-009", "How did OG look vs the C's?", "get_player_stats"),
    ("unsupported-007", "Did the Knicks win yesterday?", "get_team_stats"),
    ("exact_statistics-009", "What was the Knicks worst loss by margin?", "get_team_stats"),
    ("exact_statistics-010", "What was the Knicks highest-scoring game?", "get_team_stats"),
    ("turning_points-003", "When did the Knicks collapse against Atlanta?", "get_team_stats"),
    ("aliases_typos-010", "What was NY's worst collpase?", "get_team_stats"),
    ("exact_statistics-001", "What is the Knicks record this season?", "get_team_stats"),
    ("unsupported-006", "What are the current Eastern Conference standings?", "get_team_stats"),
]


def compact(scope: dict) -> dict:
    """Game id lists are long; record the count and the semantic filters."""
    return {**scope, "game_ids": len(scope.get("game_ids") or [])}


def summary(result) -> dict:
    return {
        "status": result.status,
        "message": result.message,
        "claims": [
            {
                "metric_id": c.metric_id,
                "value": c.value,
                "season_type": c.season_type,
                "sample_size": c.sample_size,
                "statement": c.statement,
                "limitations": c.coverage_limitations,
            }
            for c in result.claims
        ],
        "evidence": len(result.evidence),
        "scope": compact(result.scope),
    }


async def main() -> None:
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        out = []
        for case_id, question, tool in CASES:
            tools = AnalystTools(db, release, question, release.season, {})
            await tools.prepare()
            row = {
                "id": case_id,
                "question": question,
                "resolved_scope": compact(json.loads(tools.scope.model_dump_json())),
            }
            try:
                result = await tools.execute(ToolCall(name=tool, question=question))
                row["tool"] = summary(result)
            except Exception as exc:  # noqa: BLE001 - reproduction reports failures verbatim
                row["tool"] = {"error": f"{type(exc).__name__}: {exc}"}
            fallback_tools = AnalystTools(db, release, question, release.season, {})
            await fallback_tools.prepare()
            loop = AnalystLoop(fallback_tools, [])
            rendered = await loop.run(allow_model=False)
            row["fallback"] = {
                "answer": rendered["answer"],
                "route": rendered["route"],
                "warnings": rendered["warnings"],
                "claims": [c["metric_id"] for c in rendered["state"].get("claims", [])],
            }
            out.append(row)
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        target = Path(__file__).with_name("repro-before")
        target.mkdir(exist_ok=True)
        for row in out:
            (target / f"{row['id']}.json").write_text(json.dumps(row, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
