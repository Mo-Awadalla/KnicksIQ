"""Sweep date-window resolution against the local release.

No model calls. Explicit ranges, prepositions, month-days, named months and relative
windows are resolved through ``resolve_query`` and compared with windows computed from the
release's own game dates and game ids.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python \
    docs/release-evidence/llm-primary-20261021/w3-resolve/sweep_dates.py --out out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services.query_resolution import resolve_query
from sqlalchemy import select


def _date_cases(games: list[Game]) -> list[dict[str, Any]]:
    dates = sorted({game.game_date for game in games})
    first, latest = dates[0], dates[-1]

    def month_games(month: int, year: int) -> list[Game]:
        return [g for g in games if g.game_date.year == year and g.game_date.month == month]

    def window_ids(start: date, end: date) -> list[int]:
        return [g.id for g in games if start <= g.game_date <= end]

    def slice_ids(
        subset: list[Game], count: int | None, from_start: bool | None
    ) -> list[int] | None:
        if not count:
            return None
        return [g.id for g in (subset[:count] if from_start else subset[-count:])]

    march_games = month_games(3, 2026)
    may_games = month_games(5, 2026)
    boston = [g for g in games if "BOS" in {g.home_team_id, g.away_team_id}]
    march = (march_games[0].game_date, march_games[-1].game_date)
    cases = [
        (
            "range between month-days",
            "How did the Knicks do between March 1 and March 15?",
            (date(2026, 3, 1), date(2026, 3, 15)),
            None,
            None,
        ),
        (
            "range from/to month-days",
            "What did the Knicks do from March 1 to March 15?",
            (date(2026, 3, 1), date(2026, 3, 15)),
            None,
            None,
        ),
        (
            "range through month-days",
            "Knicks results March 1 through March 15",
            (date(2026, 3, 1), date(2026, 3, 15)),
            None,
            None,
        ),
        (
            "range until month-days",
            "Knicks results from March 1 until March 15",
            (date(2026, 3, 1), date(2026, 3, 15)),
            None,
            None,
        ),
        (
            "range across months",
            "Knicks results between February 20 and March 5",
            (date(2026, 2, 20), date(2026, 3, 5)),
            None,
            None,
        ),
        (
            "single month-day on",
            "How did the Knicks do on March 1?",
            (date(2026, 3, 1), date(2026, 3, 1)),
            None,
            None,
        ),
        (
            "single month-day ordinal",
            "What happened March 1st?",
            (date(2026, 3, 1), date(2026, 3, 1)),
            None,
            None,
        ),
        ("named month", "How did the Knicks do in March?", march, None, None),
        ("named month with year", "How did the Knicks do in March 2026?", march, None, None),
        ("since month-day", "Knicks results since March 1", (date(2026, 3, 1), latest), None, None),
        ("after month-day", "Knicks results after March 1", (date(2026, 3, 2), latest), None, None),
        (
            "before month-day",
            "Knicks results before March 15",
            (first, date(2026, 3, 14)),
            None,
            None,
        ),
        ("before ISO", "Knicks results before 2026-03-15", (first, date(2026, 3, 14)), None, None),
        ("since ISO", "Knicks results since 2026-03-01", (date(2026, 3, 1), latest), None, None),
        (
            "range ISO",
            "Knicks results between 2026-03-01 and 2026-03-15",
            (date(2026, 3, 1), date(2026, 3, 15)),
            None,
            None,
        ),
        (
            "single ISO",
            "Knicks results on 2026-03-01",
            (date(2026, 3, 1), date(2026, 3, 1)),
            None,
            None,
        ),
        (
            "last N games",
            "How did the Knicks do in the last 5 games?",
            None,
            (5, False),
            slice_ids(games, 5, False),
        ),
        (
            "first N games",
            "How did the Knicks do in the first 10 games?",
            None,
            (10, True),
            slice_ids(games, 10, True),
        ),
        (
            "opening N games",
            "How did the Knicks do in their opening 10 games?",
            None,
            (10, True),
            slice_ids(games, 10, True),
        ),
        (
            "last game",
            "How did the Knicks do in the last game?",
            None,
            (1, False),
            slice_ids(games, 1, False),
        ),
        (
            "first N games of month",
            "How did the Knicks do in the first 5 games of March?",
            march,
            (5, True),
            slice_ids(march_games, 5, True),
        ),
        (
            "last N games of month",
            "How did the Knicks do in the last 5 games of March?",
            march,
            (5, False),
            slice_ids(march_games, 5, False),
        ),
        (
            "first N games vs opponent",
            "How did the Knicks do in the first 10 games against Boston?",
            None,
            (10, True),
            slice_ids(boston, 10, True),
        ),
        (
            "this month",
            "How did the Knicks do this month?",
            (latest.replace(day=1), latest),
            None,
            None,
        ),
        (
            "last month",
            "How did the Knicks do last month?",
            (date(2026, 5, 1), date(2026, 5, 31)),
            None,
            [g.id for g in may_games],
        ),
        ("no month word-boundary", "What may explain the Knicks slow start?", None, None, None),
        ("in wins in March", "How many games did the Knicks win in March?", march, None, None),
    ]
    rows = []
    for kind, question, window, relative, expected_ids in cases:
        start, end = window if window else (None, None)
        if expected_ids is None and start and end and kind != "in wins in March":
            expected_ids = window_ids(start, end)
        rows.append(
            {
                "kind": kind,
                "question": question,
                "expected_start": start.isoformat() if start else None,
                "expected_end": end.isoformat() if end else None,
                "expected_relative": relative[0] if relative else None,
                "expected_from_start": relative[1] if relative else None,
                "expected_game_ids": expected_ids,
                "game_count": len(expected_ids) if expected_ids is not None else None,
            }
        )
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(DatasetRelease.status == "active").limit(1)
            )
        ).scalar_one()
        games = list(
            (
                await db.execute(
                    select(Game)
                    .where(Game.release_id == release.id)
                    .order_by(Game.game_date, Game.id)
                )
            ).scalars()
        )
        cases = _date_cases(games)
        rows = []
        for case in cases:
            resolved = await resolve_query(
                db, case["question"], intent="analyst", data_version=release.version
            )
            start = resolved.date_start.isoformat() if resolved.date_start else None
            end = resolved.date_end.isoformat() if resolved.date_end else None
            ids_ok = (
                case["expected_game_ids"] is None or resolved.game_ids == case["expected_game_ids"]
            )
            ok = (
                start == case["expected_start"]
                and end == case["expected_end"]
                and resolved.relative_game_count == case["expected_relative"]
                and ids_ok
            )
            rows.append(
                {
                    **case,
                    "resolved_start": start,
                    "resolved_end": end,
                    "resolved_relative": resolved.relative_game_count,
                    "resolved_game_ids": resolved.game_ids,
                    "resolved_game_count": len(resolved.game_ids),
                    "status": "ok" if ok else "wrong",
                }
            )
    summary = {
        "release": release.version,
        "cases": len(rows),
        "status": {
            "ok": sum(1 for row in rows if row["status"] == "ok"),
            "wrong": sum(1 for row in rows if row["status"] == "wrong"),
        },
        "wrong_date": [row for row in rows if row["status"] == "wrong"],
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "dates": rows}, indent=1))
    print(json.dumps({key: summary[key] for key in ("release", "cases", "status")}, indent=1))
    for row in summary["wrong_date"]:
        print(
            " ",
            row["kind"],
            row["resolved_start"],
            row["resolved_end"],
            "want",
            row["expected_start"],
            row["expected_end"],
            "rel",
            row["resolved_relative"],
            "want",
            row["expected_relative"],
            "games",
            row["resolved_game_count"],
            "want",
            row["game_count"],
        )


if __name__ == "__main__":
    asyncio.run(main())
