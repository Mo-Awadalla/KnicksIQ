"""A release mapping rebuilt from the seeded tools' own captured rows.

Every row's identity, digest and verified projection come from the producer's own
provenance, so a claim that cites one subset can still be held to the whole release.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluation.mapping import load_mapping
from app.evaluation.observations import canonical_digest
from app.evaluation.observations_records import EvidenceRecord
from app.evaluation.scoring_cases import _claim_payload
from app.services.analyst_provenance import (
    game_projection,
    player_stat_projection,
    row_receipt,
)
from app.services.analyst_tools import AnalystTools
from app.tests.support.evaluation_archive import VERSION


def _mapping_row(
    collection: str,
    projection: dict,
    *,
    row_id: int,
    game_id: int,
    receipt: str,
    player_id: int | None = None,
    projections: bool = True,
) -> dict:
    row = {
        "collection": collection,
        "row_sha256": canonical_digest(projection),
        "database_row_id": row_id,
        "game_id": game_id,
        "release_id": 1,
        "runtime_receipt": receipt,
        "player_id": player_id,
    }
    if projections:
        row["source_row"] = projection
    return row


def _mapping(
    tools: AnalystTools,
    tmp_path: Path,
    *,
    overrides: dict[str, dict] | None = None,
    projections: bool = True,
    name: str = "runtime-mapping.json",
):
    """The release mapping: every row's identity, digest and verified projection."""
    overrides = overrides or {}
    games = {game.id: game for game in tools.games}
    nba_games = {game.nba_game_id: game for game in tools.games}
    runtime_by_nba = {str(player.nba_player_id): player.id for _, player in tools.rows}
    players = {
        str(player.nba_player_id): {"id": player.id, "name": player.full_name}
        for _, player in tools.rows
    }

    def projected(projection: dict) -> dict:
        patched = dict(projection)
        patched.update(overrides.get(str(patched.get("nba_game_id")), {}))
        return patched

    rows: dict[str, dict] = {}
    for receipt, entry in tools.provenance.rows.items():
        collection = entry["source_collection"]
        segments = entry["canonical_id"].split(":")
        if collection == "games":
            game_id, player_id = int(entry["source_row_id"]), None
        else:
            game_id = nba_games[segments[1]].id
            player_id = runtime_by_nba[segments[2]] if segments[0] == "box" else None
        rows[entry["canonical_id"]] = _mapping_row(
            collection,
            projected(entry["source_row"]),
            row_id=int(entry["source_row_id"]),
            game_id=game_id,
            receipt=receipt,
            player_id=player_id,
            projections=projections,
        )
    for game in tools.games:
        rows.setdefault(
            f"game:{game.nba_game_id}",
            _mapping_row(
                "games",
                projected(game_projection(game)),
                row_id=game.id,
                game_id=game.id,
                receipt=row_receipt(VERSION, "games", game.id, game.id),
                projections=projections,
            ),
        )
    for stat, player in tools.rows:
        game = games[stat.game_id]
        rows.setdefault(
            f"box:{game.nba_game_id}:{player.nba_player_id}",
            _mapping_row(
                "player_game_stats",
                projected(player_stat_projection(game, stat, player)),
                row_id=stat.id,
                game_id=stat.game_id,
                receipt=row_receipt(VERSION, "player_game_stats", stat.game_id, player.id),
                player_id=player.id,
                projections=projections,
            ),
        )
    return _write_mapping(tmp_path, rows, players, name=name)


def _write_mapping(
    tmp_path: Path,
    rows: dict[str, dict],
    players: dict | None = None,
    *,
    name: str = "runtime-mapping.json",
):
    payload = {
        "version": VERSION,
        "release_id": 1,
        "rows": rows,
        "players": players or {},
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_mapping(path)


def _entry(collection: str, projection: dict, *, row_id: int, game_id: int, receipt: str) -> dict:
    return {
        "collection": collection,
        "row_sha256": canonical_digest(projection),
        "database_row_id": row_id,
        "game_id": game_id,
        "release_id": 1,
        "runtime_receipt": receipt,
        "player_id": None,
    }


def _row_record(receipt: str, projection: dict) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": receipt,
            "release_id": VERSION,
            "text": "row",
            "source_row": projection,
            "row_sha256": canonical_digest(projection),
        }
    )


def _calculation_record(
    reference: str,
    sources: list[str],
    *,
    sample_size: int,
    denominator: float | None,
    numerator: float | None = None,
    decimals: int | None = None,
    made: float | None = None,
    attempted: float | None = None,
) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "calc",
            "metadata": {
                "source_evidence_ids": sources,
                "calculation_version": "analyst-v1",
                "sample_size": sample_size,
                "denominator": denominator,
                "numerator": numerator,
                "value_decimals": decimals,
                "ingredients": {"made": made, "attempted": attempted} if made is not None else {},
            },
        }
    )


def _calculation_reference(*, subject: str, metric: str, sources: list[str], value) -> str:
    body = json.dumps([VERSION, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(body.encode()).hexdigest()


def _claim(*, subject: str, metric: str, value, denominator, sample_size: int) -> dict:
    return {
        "subject_id": subject,
        "metric_id": metric,
        "value": value,
        "denominator": denominator,
        "sample_size": sample_size,
    }


def _registry(tools: AnalystTools) -> dict[str, EvidenceRecord]:
    items = [item.model_dump(mode="json") for item in tools.evidence.values()]
    return {
        entry["evidence_id"]: EvidenceRecord.from_dict(entry)
        for entry in tools.provenance.registry(items)
    }


def _resolve(mapping, tools: AnalystTools, claim):
    (reference,) = claim.supporting_evidence_ids
    assert reference.startswith("calculation:")
    return mapping.resolve_citation(reference, _claim_payload(claim), registry=_registry(tools))


def _calculated(claims) -> list:
    """The claims whose support is one calculation receipt, so arithmetic must prove them."""
    return [
        claim
        for claim in claims
        if len(claim.supporting_evidence_ids) == 1
        and claim.supporting_evidence_ids[0].startswith("calculation:")
    ]
