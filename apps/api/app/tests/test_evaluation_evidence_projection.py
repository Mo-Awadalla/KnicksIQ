"""Authentic positive controls for evidence projections and recorded arithmetic.

The scoreline and percentage cases are graded from the response's own verified row
snapshots, so a delivered margin or split is checked against the game and shooting
numbers it cites. Each case also proves the negative: a claimed digest, a tampered
row or an undisplayed scoreline earns nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluation.assertion_checks import check_fact, numeric_tokens
from app.evaluation.labels import CanonicalFact
from app.evaluation.mapping import RuntimeMapping, load_mapping
from app.evaluation.observations import EvidenceRecord, Observation, TypedClaim, canonical_digest

VERSION = "2025-26.positive-control"


def calculation_reference(*, subject: str, metric: str, sources: list[str], value: float) -> str:
    """The recipe ``app.evaluation.mapping`` recomputes, not a second convention."""
    body = json.dumps([VERSION, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(body.encode()).hexdigest()


SCORELINE = {
    "nba_game_id": "0022500622",
    "home_team_id": "NYK",
    "away_team_id": "BKN",
    "home_score": 120,
    "away_score": 66,
    "game_date": "2026-01-21",
}

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


def _game_row(projection: dict, row_id: int) -> dict:
    return {
        "collection": "games",
        "row_sha256": canonical_digest(projection),
        "database_row_id": row_id,
        "game_id": row_id,
        "release_id": 1,
        "runtime_receipt": f"{VERSION}:game:{row_id}",
        "player_id": None,
    }


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


def _margin_claim(reference: str) -> TypedClaim:
    return TypedClaim(
        claim_id="claim:margin",
        subject_id="team:NYK",
        metric_id="win_margin",
        value=54,
        unit="points",
        population="available release archive",
        filters={},
        season="2025-26",
        season_type="regular",
        game_ids=(44,),
        window=None,
        sample_size=1,
        denominator=None,
        release_id=VERSION,
        supporting_evidence_ids=(reference,),
        statement="Knicks best win 54.",
    )


def _observation(claim: TypedClaim, record: EvidenceRecord, answer: str) -> Observation:
    return Observation(
        case_id="positive",
        turn_id="turn",
        request_id="req",
        outcome="answer",
        answer=answer,
        claims=(claim,),
        citations=(),
        analytics_status=None,
        analytics_result_count=0,
        traces=(),
        degraded=False,
        refused=False,
        route="factual_fallback",
        llm_validated=False,
        latency_ms=20.0,
        http_status=200,
        response_sha256="0" * 64,
        request={"question": "What was their best win?", "season": "2025-26"},
        sent_request_id="req",
        evidence={record.evidence_id: record},
    )


def _fact() -> CanonicalFact:
    return CanonicalFact.from_dict(
        0,
        {
            "metric": "game_score",
            "scope": "archive",
            "value": dict(SCORELINE),
            "canonical_evidence_ids": ["game:0022500622"],
        },
    )


def test_a_verified_receipt_projects_the_canonical_scoreline(tmp_path: Path) -> None:
    reference = f"{VERSION}:game:44"
    mapping = _mapping(tmp_path, {"game:0022500622": _game_row(SCORELINE, 44)})
    record = _record(reference, SCORELINE)
    observation = _observation(
        _margin_claim(reference), record, "The Knicks beat BKN 120-66 by 54 points."
    )
    check = check_fact(_fact(), observation, mapping, numeric_tokens(observation.answer))
    assert check.passed, check.failures


def test_the_projection_requires_the_scores_to_be_displayed(tmp_path: Path) -> None:
    reference = f"{VERSION}:game:44"
    mapping = _mapping(tmp_path, {"game:0022500622": _game_row(SCORELINE, 44)})
    record = _record(reference, SCORELINE)
    observation = _observation(_margin_claim(reference), record, "The Knicks won by 54 points.")
    check = check_fact(_fact(), observation, mapping, numeric_tokens(observation.answer))
    assert not check.passed
    assert {failure.code for failure in check.failures} == {"claim_not_displayed"}


def test_a_tampered_row_never_projects_a_scoreline(tmp_path: Path) -> None:
    reference = f"{VERSION}:game:44"
    mapping = _mapping(tmp_path, {"game:0022500622": _game_row(SCORELINE, 44)})
    tampered = {**SCORELINE, "home_score": 121}
    record = _record(reference, tampered)
    observation = _observation(
        _margin_claim(reference), record, "The Knicks beat BKN 120-66 by 54 points."
    )
    check = check_fact(_fact(), observation, mapping, numeric_tokens(observation.answer))
    assert [failure.code for failure in check.failures] == ["scoreline_evidence_unverified"]


def test_a_verified_row_that_contradicts_the_fact_fails(tmp_path: Path) -> None:
    reference = f"{VERSION}:game:44"
    other = {**SCORELINE, "home_score": 121}
    mapping = _mapping(tmp_path, {"game:0022500622": _game_row(other, 44)})
    record = _record(reference, other)
    observation = _observation(
        _margin_claim(reference), record, "The Knicks beat BKN 121-66 by 55 points."
    )
    check = check_fact(_fact(), observation, mapping, numeric_tokens(observation.answer))
    assert [failure.code for failure in check.failures] == ["numeric_mismatch"]


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
