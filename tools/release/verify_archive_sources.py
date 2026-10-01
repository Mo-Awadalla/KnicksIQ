"""Independently check exported canonical units and observed ranked unit receipts.

This proves represented source facts and receipt identities, never semantic
relevance, hosted provenance, approved gold, provider quality or readiness.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

BUNDLE_SHA = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(
    bundle_path: Path, unit_path: Path, policy_path: Path, observations: Path
) -> tuple[dict, dict]:
    raw = bundle_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BUNDLE_SHA, "Approved bundle identity changed")
    bundle = json.loads(gzip.decompress(raw))
    data, release = bundle["data"], bundle["manifest"]["version"]
    require(digest(data) == bundle["manifest"]["content_sha256"], "Bundle content manifest changed")
    games = {g["nba_game_id"]: g for g in data["games"]}
    players = {p["nba_player_id"]: p for p in data["players"]}
    groups = defaultdict(set)
    for identity, game in games.items():
        opponent = game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]
        groups[opponent].add(identity)
    expected_groups = {opponent: ids for opponent, ids in groups.items() if len(ids) > 1}
    expected_players = {
        r["nba_player_id"] for r in data["player_game_stats"] if r["team_id"] == "NYK"
    }
    tree = ast.parse(policy_path.read_text())
    policy = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_CURATED_PLAYER_ALIASES"
            for target in node.targets
        )
    )
    units, seen_groups, seen_players, sql_games, sql_players = {}, set(), set(), {}, set()
    for line in unit_path.read_text().splitlines():
        record = json.loads(line)
        payload = record["payload"]
        identity = record["id"]
        require(identity not in units, "Duplicate source unit")
        require(payload["data_version"] == release, "Foreign unit release")
        require("game_id" not in payload, "Unit has a representative game ID")
        require(payload["source_document_id"] == identity, "Source document identity changed")
        require(
            identity
            == "archive-unit:"
            + digest({k: v for k, v in payload.items() if k != "source_document_id"}),
            "Unit content digest changed",
        )
        require(payload["recipe"] == "archive-source-units-v1", "Unknown unit recipe")
        common_fields = {
            "recipe",
            "unit_type",
            "data_version",
            "team_ids",
            "canonical_sources",
            "text",
            "semantic_summary",
            "source_document_id",
        }
        type_fields = {
            "multigame_aggregate": {
                "aggregate_kind",
                "season",
                "opponent_id",
                "game_ids",
                "dates",
                "season_types",
                "canonical_rows",
            },
            "player_identity": {
                "player_ids",
                "player_names",
                "canonical_player",
                "aliases",
                "alias_provenance",
            },
        }
        require(
            set(payload) == common_fields | type_fields.get(payload["unit_type"], set()),
            "Unknown or missing source fields",
        )
        text = payload["text"]
        require(payload["semantic_summary"] == text, "Incomplete embedding/source text")
        if payload["unit_type"] == "multigame_aggregate":
            opponent = payload["opponent_id"]
            rows = payload["canonical_rows"]
            ids = {r["nba_game_id"] for r in rows}
            require(
                opponent not in seen_groups and opponent in expected_groups,
                "Duplicate/unknown opponent",
            )
            require(
                len(rows) == len(ids) and ids == expected_groups[opponent],
                "Incomplete opponent population",
            )
            require(
                payload["canonical_sources"] == sorted(f"game:{i}" for i in ids),
                "Inflated or missing game sources",
            )
            require(
                payload["game_ids"] == sorted(r["game_id"] for r in rows), "Game population differs"
            )
            require(
                payload["dates"] == sorted({r["game_date"] for r in rows}),
                "Date population differs",
            )
            require(
                payload["season_types"] == sorted({r["season_type"] for r in rows}),
                "Phase population differs",
            )
            wins = 0
            for row in rows:
                require(
                    set(row)
                    == {
                        "game_id",
                        "nba_game_id",
                        "game_date",
                        "season",
                        "season_type",
                        "home_team_id",
                        "away_team_id",
                        "home_score",
                        "away_score",
                        "status",
                        "source_payload_hash",
                    },
                    "Unknown or missing canonical game fields",
                )
                game = games[row["nba_game_id"]]
                for field in (
                    "game_date",
                    "season",
                    "season_type",
                    "home_team_id",
                    "away_team_id",
                    "home_score",
                    "away_score",
                    "status",
                    "source_payload_hash",
                ):
                    require(row[field] == game[field], f"Wrong canonical game field: {field}")
                require(
                    type(row["game_id"]) is int and row["game_id"] > 0, "Invalid SQL game identity"
                )
                prior = sql_games.setdefault(row["game_id"], row["nba_game_id"])
                require(prior == row["nba_game_id"], "Conflicting SQL game identity")
                win = (game["home_score"] > game["away_score"]) == (game["home_team_id"] == "NYK")
                wins += win
                line_text = (
                    f"{row['nba_game_id']} | {game['game_date']} | {game['season_type']} | "
                    f"{game['away_team_id']} {game['away_score']} at "
                    f"{game['home_team_id']} {game['home_score']} | Knicks {'W' if win else 'L'}"
                )
                require(line_text in text.splitlines(), "Canonical game fact missing from text")
            require(
                f"{wins} wins, {len(rows) - wins} losses in {len(rows)} final games" in text,
                "Wrong result count",
            )
            require(payload["team_ids"] == ["NYK", opponent], "Wrong opponent/team population")
            seen_groups.add(opponent)
            require(
                payload["aggregate_kind"] == "opponent_results"
                and payload["season"] == bundle["manifest"]["season"],
                "Wrong aggregate definition/season",
            )
            expected_header = (
                f"Knicks NYK results against {opponent} "
                f"in the {bundle['manifest']['season']} archive: "
                f"{wins} wins, {len(rows) - wins} losses in {len(rows)} final games. "
                "Complete opponent population, including every available phase."
            )
            require(
                len(text.splitlines()) == len(rows) + 1 and text.splitlines()[0] == expected_header,
                "Unsupported extra source text",
            )
        elif payload["unit_type"] == "player_identity":
            row = payload["canonical_player"]
            require(
                set(row) == {"nba_player_id", "full_name", "team_id", "position", "jersey_number"},
                "Unknown or missing canonical player fields",
            )
            nba_id = row["nba_player_id"]
            require(
                nba_id not in seen_players and nba_id in expected_players,
                "Duplicate/unknown player",
            )
            for field in ("nba_player_id", "full_name", "team_id", "position", "jersey_number"):
                require(row[field] == players[nba_id].get(field), f"Wrong player field: {field}")
            normalized = (
                unicodedata.normalize("NFKD", row["full_name"])
                .encode("ascii", "ignore")
                .decode()
                .lower()
            )
            parts = re.sub(r"[^a-z0-9]+", " ", normalized).strip().split()
            curated = {alias: name for alias, name in policy.items() if name == row["full_name"]}
            aliases = {" ".join(parts), parts[-1], f"{parts[0][0]} {parts[-1]}", *curated}
            require(payload["aliases"] == sorted(aliases), "Unsupported or missing alias")
            display = [a.upper() if a in curated and len(a) <= 3 else a for a in sorted(aliases)]
            expected_text = (
                f"Canonical player identity: {row['full_name']}; NBA player ID {nba_id}; "
                f"team {row['team_id']}. Name-derived and project-curated aliases: "
                f"{', '.join(display)}. "
                "Identity only; this does not identify a game or establish game performance."
            )
            require(text == expected_text, "Unsupported or missing identity source text")
            require(payload["player_names"] == [row["full_name"]], "Wrong player names")
            require(
                payload["team_ids"] == ([row["team_id"]] if row["team_id"] else []),
                "Wrong identity team population",
            )
            require(
                payload["alias_provenance"] == {"name_derived": True, "project_curated": curated},
                "Incorrect alias provenance",
            )
            require(payload["canonical_sources"] == [f"player:{nba_id}"], "Wrong identity source")
            require(
                f"{row['full_name']}; NBA player ID {nba_id}; team {row['team_id']}" in text,
                "Identity missing from source text",
            )
            sql_id = payload["player_ids"][0]
            require(
                len(payload["player_ids"]) == 1
                and type(sql_id) is int
                and sql_id > 0
                and sql_id not in sql_players,
                "Invalid SQL player identity",
            )
            sql_players.add(sql_id)
            seen_players.add(nba_id)
        else:
            raise ValueError("Unknown source unit type")
        units[identity] = payload
    require(
        seen_groups == set(expected_groups) and seen_players == expected_players,
        "Full archive unit inventory missing",
    )
    documents, observation_hashes = {}, {}
    for path in sorted(observations.glob("*.json")):
        observation_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        observation = json.loads(path.read_text())
        for search in observation.get("capture", {}).get("searches", []):
            ranked = search["returned_evidence_ids"]
            require(
                len(ranked) <= 5 and len(set(ranked)) == len(ranked),
                "Invalid actual ranked capture",
            )
            for receipt in search["evidence"]:
                if receipt["evidence_id"] not in ranked or not receipt["metadata"].get("unit_type"):
                    continue
                source = receipt["metadata"].get("source_document_id")
                require(source in units, "Unknown observed source unit")
                require(
                    receipt["release_id"] == release and receipt["game_id"] is None,
                    "Foreign/representative receipt",
                )
                require(receipt["text"] == units[source]["text"], "Observed source text differs")
                require(
                    all(receipt["metadata"].get(k) == v for k, v in units[source].items()),
                    "Observed source payload differs",
                )
                entry = {
                    "evidence_sha256": digest(receipt),
                    "canonical_sources": units[source]["canonical_sources"],
                }
                previous = documents.setdefault(receipt["evidence_id"], entry)
                require(previous == entry, "Conflicting observed source receipt identity")
    require(len(documents) >= 2, "Missing ranked aggregate/identity receipt proof")
    manifest = {
        "release_id": release,
        "bundle_sha256": BUNDLE_SHA,
        "documents": documents,
        "source_unit_integrity_verified": True,
        "semantic_relevance_approved": False,
    }
    result = {
        "status": "source_integrity_verified_relevance_pending",
        "bundle_sha256": BUNDLE_SHA,
        "units_sha256": hashlib.sha256(unit_path.read_bytes()).hexdigest(),
        "alias_policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "observation_sha256": observation_hashes,
        "source_units": len(units),
        "opponent_units": len(seen_groups),
        "identity_units": len(seen_players),
        "actual_ranked_unit_receipts": len(documents),
        "source_manifest_sha256": hashlib.sha256(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest(),
        "semantic_relevance_approved": False,
        "gold_frozen": False,
        "production_launch_approved": False,
        "remote_requests": 0,
    }
    return result, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "units", "alias-policy", "observations", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        result, manifest = verify(args.bundle, args.units, args.alias_policy, args.observations)
        for name, value in (
            ("source-verification.json", result),
            ("unit-runtime-source-manifest.json", manifest),
        ):
            with (args.output / name).open("x") as artifact:
                json.dump(value, artifact, indent=2, sort_keys=True)
                artifact.write("\n")
    except Exception as exc:
        with (args.output / "failure.json").open("x") as artifact:
            json.dump(
                {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)},
                artifact,
                indent=2,
            )
        raise


if __name__ == "__main__":
    main()
