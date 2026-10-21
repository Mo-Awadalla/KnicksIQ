"""Build the release runner's runtime mapping from captured observations.

Maps every runtime evidence ID that an observation cites or retrieves to the
canonical source IDs used by the frozen contract (`game:`, `box:`, `team_box:`,
`period:`, `event:`). Each mapping is provenance only: the rows a runtime
reference was computed or retrieved from. Reviewers still judge meaning.

    uv run --package knicksiq-api python tools/release/build_runtime_mapping.py \
        --observations disabled.json primary.json \
        --archive-units identity-payloads/archive_units.jsonl \
        --output runtime-mapping.json

Reads PostgreSQL via DB_URL (read-only queries). Refuses to overwrite output and
fails on any reference it cannot resolve.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

CANONICAL = re.compile(r"^(game|box|team_box|period|event):[A-Za-z0-9:]+$")
TEAM = "NYK"


class Rows:
    def __init__(self, data: dict[str, Any]):
        self.game = data["game"]  # internal id -> nba_game_id
        self.player = data["player"]  # internal id -> nba_player_id
        self.box = data["box"]  # player_game_stats id -> (game id, player id)
        self.team_box = data["team_box"]  # team_game_stats id -> (game id, team)
        self.report = data["report"]  # report id -> game id
        self.box_by_game = data["box_by_game"]  # game id -> [(player id, team)]
        self.nba_player = {str(nba): internal for internal, nba in self.player.items()}


async def pairs(db: Any, sql: str, release: int | None) -> dict[Any, Any]:
    params = {} if release is None else {"r": release}
    return {row[0]: row[1] for row in (await db.execute(text(sql), params)).all()}


async def load_rows(db_url: str, version: str) -> Rows:
    engine = create_async_engine(db_url)
    async with engine.connect() as db:
        release = (
            await db.execute(
                text("SELECT id FROM dataset_releases WHERE version=:v"), {"v": version}
            )
        ).scalar_one()
        game = await pairs(db, "SELECT id, nba_game_id FROM games WHERE release_id=:r", release)
        player = await pairs(db, "SELECT id, nba_player_id FROM players", None)
        box_rows = (
            await db.execute(
                text(
                    "SELECT id, game_id, player_id, team_id, starter FROM player_game_stats "
                    "WHERE release_id=:r"
                ),
                {"r": release},
            )
        ).all()
        team_rows = (
            await db.execute(
                text("SELECT id, game_id, team_id FROM team_game_stats WHERE release_id=:r"),
                {"r": release},
            )
        ).all()
        report = await pairs(db, "SELECT id, game_id FROM reports WHERE release_id=:r", release)
    await engine.dispose()
    box_by_game: dict[int, list[tuple[int, str, bool]]] = {}
    for _, game_id, player_id, team, starter in box_rows:
        box_by_game.setdefault(game_id, []).append((player_id, team, bool(starter)))
    return Rows(
        {
            "game": game,
            "player": player,
            "box": {row[0]: (row[1], row[2]) for row in box_rows},
            "team_box": {row[0]: (row[1], row[2]) for row in team_rows},
            "report": report,
            "box_by_game": box_by_game,
        }
    )


def canonical_strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found |= canonical_strings(item)
    elif isinstance(value, list):
        for item in value:
            found |= canonical_strings(item)
    elif isinstance(value, str) and CANONICAL.match(value):
        found.add(value)
    return found


def game_sources(rows: Rows, game_id: int) -> set[str]:
    return {f"game:{rows.game[game_id]}"}


def box_source(rows: Rows, game_id: int, player_id: int) -> str:
    return f"box:{rows.game[game_id]}:{rows.player[player_id]}"


def claim_sources(rows: Rows, claim: dict) -> set[str]:
    """Rows a verified calculation or narrative claim was computed from."""
    game_ids = claim.get("game_ids") or []
    subject = claim.get("subject_id") or ""
    metric = claim.get("metric_id") or ""
    periods = (claim.get("filters") or {}).get("periods") or []
    sources = canonical_strings(claim.get("value"))
    for game_id in game_ids:
        nba = rows.game[game_id]
        sources.add(f"game:{nba}")
        if subject.startswith("player:"):
            player_id = int(subject.split(":", 1)[1])
            if any(pid == player_id for pid, *_ in rows.box_by_game.get(game_id, [])):
                sources.add(box_source(rows, game_id, player_id))
            continue
        sources.add(f"team_box:{nba}:{TEAM}")
        if metric.endswith(":leaders") or metric in {"starts", "double_doubles:total"}:
            sources |= {
                box_source(rows, game_id, pid)
                for pid, team, _ in rows.box_by_game.get(game_id, [])
                if team == TEAM
            }
        value = claim.get("value")
        if metric == "team_comparison" and isinstance(value, dict):
            if any(key.startswith("bench_") for key in value):
                sources |= {
                    box_source(rows, game_id, pid)
                    for pid, team, starter in rows.box_by_game.get(game_id, [])
                    if team == TEAM and not starter
                }
        for period in periods:
            sources.add(f"period:{nba}:{TEAM}:{period}")
        if metric == "canonical_game_narrative":
            for entry in (claim.get("value") or {}).get("games", []):
                if entry.get("nba_game_id") == nba:
                    for row in entry.get("periods", []):
                        sources.add(f"period:{nba}:{TEAM}:{row['period']}")
    return sources


def unit_sources(rows: Rows, payload: dict) -> set[str]:
    sources: set[str] = set()
    games = [s.split(":", 1)[1] for s in payload["canonical_sources"] if s.startswith("game:")]
    sources |= {f"game:{nba}" for nba in games}
    internal_games = [gid for gid, nba in rows.game.items() if nba in set(games)]
    for source in payload["canonical_sources"]:
        if source.startswith("player:"):
            player_id = rows.nba_player[source.split(":", 1)[1]]
            for game_id in internal_games:
                if any(pid == player_id for pid, *_ in rows.box_by_game.get(game_id, [])):
                    sources.add(box_source(rows, game_id, player_id))
        elif not source.startswith("game:"):
            raise ValueError(f"Unknown archive-unit source: {source}")
    return sources


def resolve(ref: str, rows: Rows, claims: dict[str, dict], units: dict[str, dict]) -> set[str]:
    if ref.startswith("calculation:"):
        return claim_sources(rows, claims[ref])
    _, kind, rest = ref.split(":", 2)
    if kind == "narrative":
        return claim_sources(rows, claims[ref])
    if kind == "game":
        parts = rest.split(":")
        if len(parts) == 1:
            return game_sources(rows, int(parts[0]))
        if len(parts) == 3 and parts[1] == "player":
            return {box_source(rows, int(parts[0]), int(parts[2]))}
    if kind == "lexical":
        collection, _, local = rest.partition(":")
        if collection == "games":
            return game_sources(rows, int(local))
        if collection == "reports":
            return game_sources(rows, rows.report[int(local)])
        if collection == "box_scores" and local.startswith("team:"):
            game_id, team = rows.team_box[int(local.split(":", 1)[1])]
            return {f"team_box:{rows.game[game_id]}:{team}"}
        if collection == "box_scores":
            game_id, player_id = rows.box[int(local)]
            return {box_source(rows, game_id, player_id)}
        if collection == "units" and local.startswith("archive-unit:"):
            return unit_sources(rows, units[local])
    raise ValueError(f"Unresolvable runtime evidence reference: {ref}")


def references(observation: dict) -> tuple[set[str], dict[str, dict]]:
    refs: set[str] = set()
    claims: dict[str, dict] = {}
    for citation in observation["response"].get("citations", []):
        metadata = citation.get("metadata") or {}
        ref = metadata.get("evidence_id")
        if ref:
            refs.add(ref)
            if metadata.get("claim", {}).get("metric_id"):
                claims[ref] = metadata["claim"]
    for search in observation.get("capture", {}).get("searches", []):
        refs.update(search.get("returned_evidence_ids", []))
        refs.update(search.get("candidate_evidence_ids", []))
    return refs, claims


async def build(observation_paths: list[Path], units_path: Path, db_url: str) -> dict:
    captures = [json.loads(path.read_text()) for path in observation_paths]
    versions = {
        observation["response"].get("data_version")
        for capture in captures
        for observation in capture["observations"]
        if observation["response"].get("data_version")
    }
    if len(versions) != 1:
        raise ValueError(f"Observations span data versions: {sorted(versions)}")
    rows = await load_rows(db_url, versions.pop())
    units = {}
    with units_path.open() as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                units[record["id"]] = record["payload"]
    refs: set[str] = set()
    claims: dict[str, dict] = {}
    for capture in captures:
        for observation in capture["observations"]:
            found, found_claims = references(observation)
            refs |= found
            claims.update(found_claims)
    mapping = {}
    for ref in sorted(refs):
        sources = resolve(ref, rows, claims, units)
        identity_unit = ":archive-unit:" in ref and not units[
            "archive-unit:" + ref.rsplit(":", 1)[1]
        ].get("game_ids")
        if (not sources and not identity_unit) or any(
            not CANONICAL.match(source) for source in sources
        ):
            raise ValueError(f"Empty or non-canonical mapping for {ref}")
        # Player identity units name no game, so they support no game/box fact.
        mapping[ref] = sorted(sources)
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, nargs="+", required=True)
    parser.add_argument("--archive-units", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite an existing runtime mapping")
    mapping = asyncio.run(build(args.observations, args.archive_units, os.environ["DB_URL"]))
    with args.output.open("x") as handle:
        json.dump(mapping, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"references": len(mapping), "output": str(args.output)}))


if __name__ == "__main__":
    main()
