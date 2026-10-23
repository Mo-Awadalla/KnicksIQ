"""Verify locally built candidate Qdrant collections against the restored Postgres release.

Reads only localhost Qdrant and the local compose Postgres container; never a remote service.
Filters use the production default (`RAG_ARCHIVE_SOURCE_UNITS_ENABLED` unset, so false).
Run from a checkout of the tested commit with its API environment:

    uv run python verify_index.py OUTPUT.json --container kiq-rel-postgres-1
"""

import argparse
import json
import os
import subprocess

os.environ["RAG_ARCHIVE_SOURCE_UNITS_ENABLED"] = "false"

from app.services import qdrant_client as q  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

VERSION = "2025-26.20260928.1"
RELEASE_ID = 1
ROW_KINDS = {
    "knicks_games": {"game"},
    "knicks_box_scores": {"player-box", "team-box"},
    "knicks_reports": {"report"},
    "knicks_possessions": None,
}


def physical(alias: str) -> str:
    return f"{alias}__{VERSION.replace('-', '_').replace('.', '_')}"


def psql(container: str, sql: str) -> str:
    command = ["docker", "exec", container, "psql", "-U", "knicksiq", "-d", "knicksiq", "-Atc", sql]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def scroll(client: QdrantClient, name: str) -> list:
    points, offset = [], None
    while True:
        batch, offset = client.scroll(name, limit=512, offset=offset, with_vectors=True)
        points.extend(batch)
        if offset is None:
            return points


def matches(kind: str, wanted, payload: dict) -> bool:
    if kind == "game_ids":
        return payload.get("game_id") == wanted
    if kind == "dates":
        return payload.get("date") == wanted
    if kind == "team_ids":
        return bool(set(wanted) & set(payload.get("team_ids", [])))
    if kind == "player_ids":
        return bool(set(wanted) & set(payload.get("player_ids", [])))
    return payload.get("start_period", 0) <= wanted <= payload.get("end_period", 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    scoped = f"join games g on g.id = t.game_id where g.release_id = {RELEASE_ID}"
    games = int(psql(args.container, f"select count(*) from games where release_id = {RELEASE_ID}"))
    teams = int(psql(args.container, f"select count(*) from team_game_stats t {scoped}"))
    players = int(psql(args.container, f"select count(*) from player_game_stats t {scoped}"))
    reports = int(psql(args.container, f"select count(*) from reports t {scoped}"))
    game_ids = {
        int(v)
        for v in psql(args.container, f"select id from games where release_id = {RELEASE_ID}").split()
    }
    expected_rows = {
        "knicks_games": games,
        "knicks_box_scores": teams + players,
        "knicks_reports": reports,
    }
    client = QdrantClient(host="localhost", port=6333)
    result: dict = {
        "data_version": VERSION,
        "filter_mode": "production default, archive-unit filters off",
        "db_rows": expected_rows,
        "collections": {},
    }
    failures: list[str] = []
    for alias, row_kinds in ROW_KINDS.items():
        name = physical(alias)
        points = scroll(client, name)
        kind_of = [str(p.payload.get("chunk_id", "")).split(":")[0] for p in points]
        rows = [p for p, k in zip(points, kind_of, strict=True) if row_kinds is None or k in row_kinds]
        units = [p for p, k in zip(points, kind_of, strict=True) if k == "archive-unit"]
        entry: dict = {
            "physical": name,
            "points": len(points),
            "row_points": len(rows),
            "archive_units": len(units),
            "vector_sizes": sorted({len(p.vector) for p in points}),
            "filters": [],
        }
        if alias in expected_rows and len(rows) != expected_rows[alias]:
            failures.append(f"{alias}: {len(rows)} row points, DB has {expected_rows[alias]}")
        if len(rows) + len(units) != len(points):
            failures.append(f"{alias}: points of unknown kind")
        versions = {p.payload.get("data_version") for p in points}
        if versions != {VERSION}:
            failures.append(f"{alias}: data_versions {sorted(map(str, versions))}")
        stray = {p.payload.get("game_id") for p in rows} - game_ids
        stray |= {g for p in units for g in p.payload.get("game_ids", [])} - game_ids
        if stray:
            failures.append(f"{alias}: game ids not in restored release: {sorted(stray)[:5]}")
        wrong = client.count(
            name, count_filter=q.build_qdrant_filter({"data_version": "wrong-release"}), exact=True
        ).count
        entry["wrong_release_count"] = wrong
        if wrong:
            failures.append(f"{alias}: wrong-release filter returned {wrong}")
        sample = rows[0].payload
        selectors = [("game_ids", [sample["game_id"]], sample["game_id"])]
        selectors.append(("dates", [sample["date"]], sample["date"]))
        if sample.get("team_ids"):
            selectors.append(("team_ids", sample["team_ids"], sample["team_ids"]))
        if sample.get("player_ids"):
            selectors.append(("player_ids", sample["player_ids"], sample["player_ids"]))
        if sample.get("start_period"):
            selectors.append(("periods", [sample["start_period"]], sample["start_period"]))
        for kind, filter_value, wanted in selectors:
            actual = client.count(
                name,
                count_filter=q.build_qdrant_filter({kind: filter_value, "data_version": VERSION}),
                exact=True,
            ).count
            want = sum(1 for p in points if matches(kind, wanted, p.payload))
            entry["filters"].append({"filter": kind, "actual": actual, "expected": want})
            if actual != want or want == 0:
                failures.append(f"{alias}: {kind} filter {actual} != {want}")
        result["collections"][alias] = entry
    result["passed"] = not failures
    result["failures"] = failures
    with open(args.output, "w") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": result["passed"], "failures": failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
