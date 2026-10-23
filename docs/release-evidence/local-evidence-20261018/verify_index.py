"""Verify candidate Qdrant collections on a local instance against the restored Postgres release.

Reads only localhost Qdrant and the local compose Postgres container. Never contacts remote
Qdrant or providers.
Usage (from a checkout with the API environment): python verify_index.py OUTPUT.json
"""

import json
import subprocess
import sys

from app.services import qdrant_client as q
from qdrant_client import QdrantClient

VERSION = "2025-26.20260928.1"
RELEASE_ID = 1
POSTGRES_CONTAINER = "kiq-e003-postgres-1"
PHYSICAL = {
    "knicks_games": "knicks_games__2025_26_20260928_1",
    "knicks_box_scores": "knicks_box_scores__2025_26_20260928_1",
    "knicks_possessions": "knicks_possessions__2025_26_20260928_1",
    "knicks_reports": "knicks_reports__2025_26_20260928_1",
}


def psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", POSTGRES_CONTAINER, "psql", "-U", "knicksiq", "-d", "knicksiq", "-Atc", sql],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    scoped = f"join games g on g.id = t.game_id where g.release_id = {RELEASE_ID}"
    games = int(psql(f"select count(*) from games where release_id = {RELEASE_ID}"))
    teams = int(psql(f"select count(*) from team_game_stats t {scoped}"))
    players = int(psql(f"select count(*) from player_game_stats t {scoped}"))
    reports = int(psql(f"select count(*) from reports t {scoped}"))
    game_ids = {int(v) for v in psql(f"select id from games where release_id = {RELEASE_ID}").split()}
    expected = {
        "knicks_games": games,
        "knicks_reports": reports,
        "knicks_box_scores": teams + players,
    }
    client = QdrantClient(host="localhost", port=6333)
    result: dict = {"data_version": VERSION, "db_rows": expected, "collections": {}}
    failures: list[str] = []
    for alias, name in PHYSICAL.items():
        points = scroll(client, name)
        entry: dict = {
            "physical": name,
            "points": len(points),
            "vector_sizes": sorted({len(p.vector) for p in points}),
            "filters": [],
        }
        if alias in expected and len(points) != expected[alias]:
            failures.append(f"{alias}: {len(points)} points, DB has {expected[alias]}")
        versions = {p.payload.get("data_version") for p in points}
        if versions != {VERSION}:
            failures.append(f"{alias}: data_versions {sorted(map(str, versions))}")
        stray = {p.payload.get("game_id") for p in points} - game_ids
        if stray:
            failures.append(f"{alias}: game_ids not in restored release: {sorted(stray)[:5]}")
        wrong = client.count(
            name, count_filter=q.build_qdrant_filter({"data_version": "wrong-release"}), exact=True
        ).count
        entry["wrong_release_count"] = wrong
        if wrong:
            failures.append(f"{alias}: wrong-release filter returned {wrong}")
        sample = points[0].payload
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
    with open(sys.argv[1], "w") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
