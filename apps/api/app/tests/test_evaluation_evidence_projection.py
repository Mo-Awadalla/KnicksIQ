"""Percentage receipts are verified against their shooting ingredients."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluation.mapping import RuntimeMapping, load_mapping
from app.evaluation.observations import EvidenceRecord, canonical_digest

VERSION = "2025-26.positive-control"


def calculation_reference(*, subject: str, metric: str, sources: list[str], value: float) -> str:
    """The recipe ``app.evaluation.mapping`` recomputes, not a second convention."""
    body = json.dumps([VERSION, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(body.encode()).hexdigest()


SHOOTING = {
    "nba_game_id": "0022500622",
    "team_id": "NYK",
    "field_goals_made": 40,
    "field_goals_attempted": 80,
    "three_pointers_made": 30,
    "three_pointers_attempted": 100,
    "free_throws_made": 10,
    "free_throws_attempted": 12,
}


def _mapping(tmp_path: Path, rows: dict[str, dict]) -> RuntimeMapping:
    payload = {
        "scope": "positive control",
        "version": VERSION,
        "release_id": 1,
        "bundle_sha256": "f" * 64,
        "verified_source_references": 0,
        "rows": rows,
        "players": {"1628973": {"id": 134, "name": "Jalen Brunson"}},
    }
    path = tmp_path / "runtime-mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_mapping(path)


def _team_row(projection: dict, row_id: int, game_id: int) -> dict:
    return {
        "collection": "team_game_stats",
        "row_sha256": canonical_digest(projection),
        "database_row_id": row_id,
        "game_id": game_id,
        "release_id": 1,
        "runtime_receipt": f"{VERSION}:team_box:{game_id}:team:{row_id}",
        "player_id": None,
    }


def _record(reference: str, projection: dict, *, row_sha256: str | None = None) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "row",
            "source_row": projection,
            "row_sha256": row_sha256 or canonical_digest(projection),
        }
    )


def _percent_mapping(tmp_path: Path) -> RuntimeMapping:
    return _mapping(tmp_path, {"team_box:0022500622:NYK": _team_row(SHOOTING, 44, 44)})


def test_a_percentage_is_verified_from_its_own_ingredients(tmp_path: Path) -> None:
    mapping = _percent_mapping(tmp_path)
    sources = [f"{VERSION}:team_box:44:team:44"]
    value = 30.0
    reference = calculation_reference(
        subject="team:NYK",
        metric="three_pointers_made:percentage",
        sources=sources,
        value=value,
    )
    claim = {
        "subject_id": "team:NYK",
        "metric_id": "three_pointers_made:percentage",
        "value": value,
        "denominator": 1.0,
        "sample_size": 1,
        "unit": "percent",
    }
    record = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "calc",
            "metadata": {
                "source_evidence_ids": sources,
                "calculation_version": "analyst-v1",
                "sample_size": 1,
                "denominator": 1.0,
                "value_decimals": 4,
                "ingredients": {"made": 30, "attempted": 100},
            },
        }
    )
    source = _record(sources[0], SHOOTING)
    resolution = mapping.resolve_citation(
        reference, claim, registry={reference: record, sources[0]: source}
    )
    assert not resolution.problems and not resolution.unverified

    tampered = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "calc",
            "metadata": {
                "source_evidence_ids": sources,
                "calculation_version": "analyst-v1",
                "sample_size": 1,
                "denominator": 1.0,
                "value_decimals": 4,
                "ingredients": {"made": 31, "attempted": 100},
            },
        }
    )
    resolution = mapping.resolve_citation(
        reference, claim, registry={reference: tampered, sources[0]: source}
    )
    assert "calculation_arithmetic_mismatch" in resolution.problems
