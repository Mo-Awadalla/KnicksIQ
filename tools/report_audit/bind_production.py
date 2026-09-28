"""Read-only production snapshot and comparison; never approve or activate reports."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from audit import audit, digest

TABLES = {
    "events": "game_events",
    "games": "games",
    "period_scores": "period_scores",
    "player_game_stats": "player_game_stats",
    "players": "players",
    "reports": "reports",
    "team_game_stats": "team_game_stats",
    "teams": "teams",
}


def safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def compare(expected, actual):
    left, right = Counter(digest(row) for row in expected), Counter(digest(row) for row in actual)
    return {
        "expected_rows": len(expected),
        "actual_rows": len(actual),
        "missing_or_changed": sum((left - right).values()),
        "unexpected": sum((right - left).values()),
        "matches": left == right,
        "expected_rows_sha256": digest(sorted(left.items())),
        "actual_rows_sha256": digest(sorted(right.items())),
    }


async def bind(baseline_path, output):
    from app.core.config import get_settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    baseline_raw = baseline_path.read_bytes()
    baseline = json.loads(baseline_raw)
    engine = create_async_engine(get_settings().effective_db_url, echo=False)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            read_only = await connection.scalar(text("SHOW transaction_read_only"))
            if read_only != "on":
                raise RuntimeError("Read-only transaction not established")
            releases = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, version, manifest_sha256 FROM dataset_releases "
                            "WHERE status = 'active'"
                        )
                    )
                )
                .mappings()
                .all()
            )
            if len(releases) != 1:
                raise ValueError("Expected exactly one active release")
            release = dict(releases[0])
            snapshots = {}
            for name, table in TABLES.items():
                if name in {"players", "teams"}:
                    query = f"SELECT * FROM {table}"
                elif name == "events":
                    query = (
                        "SELECT e.* FROM game_events e JOIN games g ON g.id=e.game_id "
                        "WHERE g.release_id=:release_id"
                    )
                else:
                    query = f"SELECT * FROM {table} WHERE release_id=:release_id"
                snapshots[name] = [
                    dict(row)
                    for row in (
                        await connection.execute(text(query), {"release_id": release["id"]})
                    ).mappings()
                ]
            await connection.rollback()
    finally:
        await engine.dispose()
    game_ids = {r["id"]: r["nba_game_id"] for r in snapshots["games"]}
    player_ids = {r["id"]: r["nba_player_id"] for r in snapshots["players"]}
    projected, comparisons = {}, {}
    for name, rows in snapshots.items():
        fields = baseline["data"][name][0].keys()
        projected[name] = []
        for row in rows:
            row = dict(row)
            if "game_id" in row:
                row["nba_game_id"] = game_ids[row["game_id"]]
            if "player_id" in row:
                row["nba_player_id"] = player_ids.get(row["player_id"])
            projected[name].append({key: safe(row[key]) for key in fields})
        comparisons[name] = compare(baseline["data"][name], projected[name])
    # Use freshly fetched rows for the audit, retaining only the baseline manifest
    # and expected content hashes. A mismatch must remain visible, never normalized away.
    production = copy.deepcopy(baseline)
    production["data"] = projected
    result, _ = audit(production)
    result["baseline_identity"] = "fresh_production_read_only_repeatable_read_snapshot"
    raw_reports = [{k: safe(v) for k, v in r.items()} for r in snapshots["reports"]]
    raw_reports.sort(key=lambda r: r["id"])
    binding = {
        "captured_at": datetime.now(UTC).isoformat(),
        "transaction_read_only": read_only,
        "isolation_level": "repeatable read",
        "active_release": release,
        "baseline_file": str(baseline_path),
        "baseline_file_sha256": hashlib.sha256(baseline_raw).hexdigest(),
        "collections": comparisons,
        "all_rows_match": all(c["matches"] for c in comparisons.values()),
        "production_report_snapshot_sha256": digest(raw_reports),
        "report_audit": result,
        "production_writes": False,
        "owner_approval": None,
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in [
        ("production-binding.json", binding),
        ("production-rollback-reports.json", raw_reports),
    ]:
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "all_rows_match": binding["all_rows_match"],
                "collections": {k: v["matches"] for k, v in comparisons.items()},
                "audit": result["summary"],
            }
        )
    )
    if not binding["all_rows_match"]:
        raise ValueError("Production differs from baseline; inspect binding before approval")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(bind(args.baseline, args.output))


if __name__ == "__main__":
    main()
