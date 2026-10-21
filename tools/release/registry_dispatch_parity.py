"""Compare tool dispatch outputs between two source trees against the local release.

Used to prove the registry refactor did not change any of the six existing tools. The same call
matrix runs against a base tree and the branch tree; each result is hashed canonically.

    DB_URL=... uv run python tools/release/registry_dispatch_parity.py \
        --root /path/to/tree --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

CASES: tuple[dict[str, Any], ...] = (
    {
        "case": "team_total",
        "call": {
            "name": "get_team_stats",
            "question": "What was the Knicks record this season?",
            "aggregation": "total",
        },
    },
    {
        "case": "team_average",
        "call": {
            "name": "get_team_stats",
            "question": "What was the Knicks average margin?",
            "aggregation": "average",
        },
    },
    {
        "case": "player",
        "call": {
            "name": "get_player_stats",
            "question": "How many points did Jalen Brunson average?",
        },
    },
    {
        "case": "discover",
        "call": {
            "name": "discover_facts",
            "question": "What was interesting about the Knicks season?",
        },
    },
    {
        "case": "archive",
        "call": {
            "name": "search_archive",
            "question": "How did the Knicks lose the lead against Boston?",
        },
    },
    {
        "case": "compare",
        "call": {
            "name": "compare_windows",
            "question": "How did the Knicks do at home?",
            "baseline_question": "How did the Knicks do on the road?",
        },
    },
    {
        "case": "periods_guard",
        "call": {
            "name": "get_team_stats",
            "question": "How many points did the Knicks score in the third quarter?",
        },
    },
    {
        "case": "empty_games",
        "call": {
            "name": "get_team_stats",
            "question": "How did the Knicks do against Seattle in 2025-26?",
        },
    },
    {
        "case": "missing_player",
        "call": {"name": "get_player_stats", "question": "How many points per game this season?"},
    },
    {
        "case": "season_guard",
        "call": {"name": "get_team_stats", "question": "How did the Knicks do in 2024-25?"},
    },
    {
        "case": "unissued_evidence",
        "call": {"name": "get_evidence", "question": "expand", "evidence_ids": ["not-issued"]},
    },
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def summarize(result: Any) -> dict[str, Any]:
    body = result.model_dump(mode="json")
    return {
        "status": result.status,
        "message": result.message,
        "choices": result.choices,
        "claims": len(result.claims),
        "evidence": len(result.evidence),
        "sha256": digest(body),
    }


async def run() -> dict[str, Any]:
    from app.models.dataset_release import DatasetRelease
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["DB_URL"], future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    app_file = sys.modules["app"].__file__
    assert app_file is not None
    results: dict[str, Any] = {"app": str(Path(app_file).resolve()), "cases": {}}
    try:
        async with maker() as db:
            release = (
                await db.execute(
                    select(DatasetRelease).where(
                        DatasetRelease.status == "active",
                        DatasetRelease.validation_passed.is_(True),
                    )
                )
            ).scalar_one()
            db.expunge(release)
        for item in CASES:
            async with maker() as db:
                tools = AnalystTools(db, release, item["call"]["question"], release.season, {})
                await tools.prepare()
                result = await tools.execute(ToolCall(**item["call"]))
                results["cases"][item["case"]] = summarize(result)
        async with maker() as db:
            team = ToolCall(
                name="get_team_stats",
                question="What was the Knicks record this season?",
                aggregation="total",
            )
            tools = AnalystTools(db, release, team.question, release.season, {})
            await tools.prepare()
            first = await tools.execute(team)
            ids = [item.evidence_id for item in first.evidence[:2]]
            second = await tools.execute(
                ToolCall(name="get_evidence", question="expand", evidence_ids=ids)
            )
            results["cases"]["issued_evidence"] = summarize(second)
            results["cases"]["issued_evidence"]["requested"] = len(ids)
    finally:
        await engine.dispose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "packages/basketball-core/src"))
    sys.path.insert(0, str(root / "apps/api"))
    report = asyncio.run(run())
    if not Path(report["app"]).is_relative_to(root):
        raise SystemExit(f"imported app from {report['app']}, expected under {root}")
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["cases"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
