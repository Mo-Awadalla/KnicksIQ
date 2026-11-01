"""Period and team rows prove their own claims: receipts, snapshots, arithmetic.

Written before the period/team provenance change. The cases drive the real split
operations over seeded release rows and the real evaluation verifier, so period
scoring and shooting splits must cite and capture the rows they actually read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.evaluation.mapping import RuntimeMapping, load_mapping
from app.evaluation.observations import EvidenceRecord
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_provenance import (
    PERIOD_SCORE_FIELDS,
    TEAM_GAME_STAT_FIELDS,
    row_receipt,
)
from app.services.analyst_provenance import (
    canonical_digest as provenance_digest,
)
from app.services.analyst_team_splits import period_scoring, result_split
from app.services.analyst_tools import AnalystTools
from sqlalchemy import select

VERSION = "2025-26.row-provenance-test"


def calculation_reference(*, subject: str, metric: str, sources: list[str], value: float) -> str:
    body = json.dumps([VERSION, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(body.encode()).hexdigest()


ARCHIVE = (
    ("2025-11-05", "NYK", "BOS", 112, 104),
    ("2025-11-20", "BOS", "NYK", 100, 108),
    ("2025-12-05", "NYK", "BOS", 118, 110),
    ("2025-12-15", "BOS", "NYK", 120, 99),
    ("2025-12-31", "SAS", "NYK", 134, 132),
    ("2026-01-02", "NYK", "ATL", 99, 111),
    ("2026-01-05", "NYK", "MIA", 105, 98),
)


async def _seed(db_session) -> DatasetRelease:
    release = DatasetRelease(
        version=VERSION,
        season="2025-26",
        source="test",
        manifest_sha256="d" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    player = (
        await db_session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
    ).scalar_one()
    for index, (day, home, away, home_score, away_score) in enumerate(ARCHIVE):
        game = Game(
            release_id=release.id,
            nba_game_id=f"00225000{index:02d}",
            season="2025-26",
            game_date=date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type="regular",
            data_status="analysis_ready",
            source_name="test",
            source_game_id=f"00225000{index:02d}",
            source_url="https://example.test/game",
            source_payload_hash="0" * 64,
            source_fetched_at=datetime.now(UTC),
        )
        db_session.add(game)
        await db_session.flush()
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                starter=True,
                position="G",
                minutes=34.0,
                points=20 + index,
                rebounds=4,
                assists=6,
                turnovers=2,
                three_pointers_made=2,
                three_pointers_attempted=5,
                field_goals_made=7,
                field_goals_attempted=15,
                free_throws_made=4,
                free_throws_attempted=4,
            )
        )
        db_session.add(
            TeamGameStat(
                release_id=release.id,
                game_id=game.id,
                team_id="NYK",
                points=home_score if home == "NYK" else away_score,
                field_goals_made=7 + index,
                field_goals_attempted=15 + index,
                three_pointers_made=2,
                three_pointers_attempted=5,
                free_throws_made=4,
                free_throws_attempted=5,
                offensive_rebounds=3,
                defensive_rebounds=9,
                rebounds=12,
                assists=8,
                steals=2,
                blocks=1,
                turnovers=3,
                personal_fouls=4,
                plus_minus=index - 2,
            )
        )
        db_session.add(
            PeriodScore(release_id=release.id, game_id=game.id, team_id="NYK", period=1, points=25)
        )
    await db_session.commit()
    return release


async def _tools(db_session, question: str) -> AnalystTools:
    release = await _seed(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    return tools


def _period_snapshot(points: int = 25, *, period: int = 1) -> dict[str, object]:
    return {"nba_game_id": "0022500003", "period": period, "points": points, "team_id": "NYK"}


def _team_snapshot(game_id: str, *, made: int, attempted: int) -> dict[str, object]:
    snapshot: dict[str, object] = dict.fromkeys(TEAM_GAME_STAT_FIELDS, 0)
    snapshot["nba_game_id"] = game_id
    snapshot["team_id"] = "NYK"
    snapshot["three_pointers_made"] = made
    snapshot["three_pointers_attempted"] = attempted
    return snapshot


def _row_entry(
    collection: str,
    projection: dict[str, object],
    *,
    row_id: int,
    game_id: int,
    receipt: str | None,
) -> dict[str, object]:
    return {
        "collection": collection,
        "row_sha256": provenance_digest(projection),
        "database_row_id": row_id,
        "game_id": game_id,
        "release_id": 1,
        "runtime_receipt": receipt,
        "player_id": None,
    }


def _mapping(tmp_path: Path, rows: dict[str, dict]) -> RuntimeMapping:
    payload = {
        "scope": "row provenance test",
        "version": VERSION,
        "release_id": 1,
        "bundle_sha256": "e" * 64,
        "verified_source_references": 0,
        "rows": rows,
        "players": {},
    }
    path = tmp_path / "runtime-mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_mapping(path)


def _calc_record(reference: str, sources: list[str], **metadata: object) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "calc",
            "metadata": {
                "source_evidence_ids": sources,
                "calculation_version": "analyst-v1",
                **metadata,
            },
        }
    )


def _source_record(
    receipt: str, snapshot: dict, *, row_sha256: str | None = None
) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": receipt,
            "release_id": VERSION,
            "text": "row",
            "source_row": snapshot,
            "row_sha256": row_sha256 or provenance_digest(snapshot),
        }
    )


def test_evaluator_recomputes_a_period_numerator_from_verified_rows(tmp_path: Path) -> None:
    snapshot = _period_snapshot()
    receipt = row_receipt(VERSION, "period_scores", 12, 34)
    mapping = _mapping(
        tmp_path,
        {
            "period:0022500003:NYK:1": _row_entry(
                "period_scores", snapshot, row_id=34, game_id=12, receipt=receipt
            )
        },
    )
    sources = [receipt]
    claim = {
        "subject_id": "team:NYK",
        "metric_id": "period:points",
        "value": 25.0,
        "denominator": 1.0,
        "sample_size": 1,
    }
    reference = calculation_reference(
        subject="team:NYK", metric="period:points", sources=sources, value=25.0
    )
    verified = _calc_record(reference, sources, sample_size=1, denominator=1.0, numerator=25.0)
    source = _source_record(receipt, snapshot)
    assert not mapping.resolve_citation(
        reference, claim, registry={reference: verified, receipt: source}
    ).problems

    # A self-consistent numerator/value pair is still wrong when the verified row says 25.
    inconsistent = calculation_reference(
        subject="team:NYK", metric="period:points", sources=sources, value=26.0
    )
    tampered = _calc_record(inconsistent, sources, sample_size=1, denominator=1.0, numerator=26.0)
    resolution = mapping.resolve_citation(
        inconsistent,
        {**claim, "value": 26.0},
        registry={inconsistent: tampered, receipt: source},
    )
    assert "calculation_arithmetic_mismatch" in resolution.problems


def test_evaluator_recomputes_a_shooting_split_from_team_rows(tmp_path: Path) -> None:
    first = _team_snapshot("0022500003", made=10, attempted=30)
    second = _team_snapshot("0022500018", made=7, attempted=20)
    first_receipt = row_receipt(VERSION, "team_game_stats", 12, 34)
    second_receipt = row_receipt(VERSION, "team_game_stats", 13, 35)
    rows = {
        "team_box:0022500003:NYK": _row_entry(
            "team_game_stats", first, row_id=34, game_id=12, receipt=first_receipt
        ),
        "team_box:0022500018:NYK": _row_entry(
            "team_game_stats", second, row_id=35, game_id=13, receipt=second_receipt
        ),
    }
    mapping = _mapping(tmp_path, rows)
    sources = [first_receipt, second_receipt]
    registry = {
        first_receipt: _source_record(first_receipt, first),
        second_receipt: _source_record(second_receipt, second),
    }
    claim = {
        "subject_id": "team:NYK",
        "metric_id": "three_pointers_made:percentage",
        "value": 34.0,
        "denominator": 2.0,
        "sample_size": 2,
    }
    reference = calculation_reference(
        subject="team:NYK",
        metric="three_pointers_made:percentage",
        sources=sources,
        value=34.0,
    )
    verified = _calc_record(
        reference,
        sources,
        sample_size=2,
        denominator=2.0,
        numerator=None,
        value_decimals=4,
        ingredients={"made": 17, "attempted": 50},
    )
    assert not mapping.resolve_citation(
        reference, claim, registry={reference: verified, **registry}
    ).problems

    # Ingredients and value agree with each other but contradict the verified team rows.
    inconsistent = calculation_reference(
        subject="team:NYK",
        metric="three_pointers_made:percentage",
        sources=sources,
        value=36.0,
    )
    tampered = _calc_record(
        inconsistent,
        sources,
        sample_size=2,
        denominator=2.0,
        numerator=None,
        value_decimals=4,
        ingredients={"made": 18, "attempted": 50},
    )
    resolution = mapping.resolve_citation(
        inconsistent, {**claim, "value": 36.0}, registry={inconsistent: tampered, **registry}
    )
    assert "calculation_arithmetic_mismatch" in resolution.problems


def test_mapping_resolves_period_and_team_receipts_by_their_rows(tmp_path: Path) -> None:
    rows = {
        "game:0022500003": _row_entry(
            "games", {"nba_game_id": "0022500003"}, row_id=12, game_id=12, receipt=None
        ),
        "team_box:0022500003:NYK": _row_entry(
            "team_game_stats",
            _team_snapshot("0022500003", made=10, attempted=30),
            row_id=34,
            game_id=12,
            receipt=None,
        ),
        "period:0022500003:NYK:1": _row_entry(
            "period_scores", _period_snapshot(), row_id=35, game_id=12, receipt=None
        ),
        "period:0022500003:NYK:2": _row_entry(
            "period_scores", _period_snapshot(period=2), row_id=36, game_id=12, receipt=None
        ),
    }
    mapping = _mapping(tmp_path, rows)
    team = mapping.resolve_citation(f"{VERSION}:team_box:12:team:34", None)
    assert team.kind == "receipt" and not team.problems
    assert team.canonical_ids == ("team_box:0022500003:NYK",)
    period = mapping.resolve_citation(f"{VERSION}:period:12:period:36", None)
    assert period.kind == "receipt" and not period.problems
    assert period.canonical_ids == ("period:0022500003:NYK:2",)
    assert mapping.resolve_citation(f"{VERSION}:team_box:12:team:99", None).kind == "unresolved"


def _claim_sources(tools: AnalystTools, claim) -> list[str]:
    references = list(claim.supporting_evidence_ids)
    if len(references) == 1 and references[0].startswith("calculation:"):
        return list(tools.evidence[references[0]].metadata["source_evidence_ids"])
    return references


async def test_period_scoring_cites_and_captures_its_own_period_rows(db_session) -> None:
    tools = await _tools(db_session, "What was the Knicks' average first-quarter scoring?")
    assert tools.scope is not None and tools.scope.operation == "period_scoring"
    result = await period_scoring(tools, tools.scope)
    (claim,) = result.claims
    sources = _claim_sources(tools, claim)
    period_rows = [
        row for row in (await db_session.execute(select(PeriodScore))).scalars() if row.period == 1
    ]
    expected = {row_receipt(VERSION, "period_scores", row.game_id, row.id) for row in period_rows}
    assert set(sources) == expected
    entries = tools.provenance.registry([{"evidence_id": source} for source in sources])
    assert {entry["source_collection"] for entry in entries} == {"period_scores"}
    for entry in entries:
        assert set(entry["source_row"]) == set(PERIOD_SCORE_FIELDS)
        assert entry["row_sha256"] == provenance_digest(entry["source_row"])
        assert entry["canonical_id"].startswith("period:")
    total = sum(entry["source_row"]["points"] for entry in entries)
    (calculation,) = [tools.evidence[ref] for ref in claim.supporting_evidence_ids]
    assert calculation.evidence_id.startswith("calculation:")
    assert calculation.metadata["numerator"] == total
    assert calculation.metadata["denominator"] == len(entries) == claim.denominator
    assert claim.value == total / len(entries)


async def test_result_split_cites_and_captures_its_own_team_rows(db_session) -> None:
    tools = await _tools(db_session, "Did the Knicks shoot better in wins or losses?")
    assert tools.scope is not None and tools.scope.operation == "result_split"
    result = await result_split(tools, tools.scope)
    claims = {claim.filters["game_result"]: claim for claim in result.claims}
    assert set(claims) == {"win", "loss"}
    for claim in claims.values():
        sources = _claim_sources(tools, claim)
        entries = tools.provenance.registry([{"evidence_id": source} for source in sources])
        assert entries and {entry["source_collection"] for entry in entries} == {"team_game_stats"}
        made = attempted = 0
        for entry in entries:
            assert set(entry["source_row"]) == set(TEAM_GAME_STAT_FIELDS)
            assert entry["row_sha256"] == provenance_digest(entry["source_row"])
            assert entry["canonical_id"].startswith("team_box:")
            made += entry["source_row"]["field_goals_made"]
            attempted += entry["source_row"]["field_goals_attempted"]
        assert claim.eligibility["made"] == made
        assert claim.eligibility["attempted"] == attempted
        value = claim.value
        assert isinstance(value, (int, float)), value
        assert abs(value - 100 * made / attempted) < 1e-4
        assert claim.denominator == len(entries)
    win_receipt = tools.evidence[claims["win"].supporting_evidence_ids[0]]
    assert win_receipt.evidence_id.startswith("calculation:")
    assert win_receipt.metadata["numerator"] is None
    assert win_receipt.metadata["ingredients"] == {
        "made": claims["win"].eligibility["made"],
        "attempted": claims["win"].eligibility["attempted"],
    }


def test_period_arithmetic_rejects_final_score_sources(tmp_path: Path) -> None:
    game_receipt = row_receipt(VERSION, "games", 12, 12)
    snapshot = {"nba_game_id": "0022500003", "home_score": 60, "away_score": 50}
    rows = {
        "game:0022500003": _row_entry(
            "games", snapshot, row_id=12, game_id=12, receipt=game_receipt
        )
    }
    mapping = _mapping(tmp_path, rows)
    sources = [game_receipt]
    reference = calculation_reference(
        subject="team:NYK", metric="period:points", sources=sources, value=60.0
    )
    record = _calc_record(reference, sources, sample_size=1, denominator=1.0, numerator=60.0)
    resolution = mapping.resolve_citation(
        reference,
        {
            "subject_id": "team:NYK",
            "metric_id": "period:points",
            "value": 60.0,
            "denominator": 1.0,
            "sample_size": 1,
        },
        registry={reference: record, game_receipt: _source_record(game_receipt, snapshot)},
    )
    assert "calculation_expansion_mismatch" in resolution.problems


def test_a_tampered_team_snapshot_never_passes(tmp_path: Path) -> None:
    snapshot = _team_snapshot("0022500003", made=10, attempted=30)
    receipt = row_receipt(VERSION, "team_game_stats", 12, 34)
    mapping = _mapping(
        tmp_path,
        {
            "team_box:0022500003:NYK": _row_entry(
                "team_game_stats", snapshot, row_id=34, game_id=12, receipt=receipt
            )
        },
    )
    sources = [receipt]
    value = 100 * 10 / 30
    reference = calculation_reference(
        subject="team:NYK",
        metric="three_pointers_made:percentage",
        sources=sources,
        value=value,
    )
    record = _calc_record(
        reference,
        sources,
        sample_size=1,
        denominator=1.0,
        numerator=None,
        value_decimals=4,
        ingredients={"made": 10, "attempted": 30},
    )
    tampered = _source_record(
        receipt, {**snapshot, "three_pointers_made": 11}, row_sha256=provenance_digest(snapshot)
    )
    resolution = mapping.resolve_citation(
        reference,
        {
            "subject_id": "team:NYK",
            "metric_id": "three_pointers_made:percentage",
            "value": value,
            "denominator": 1.0,
            "sample_size": 1,
        },
        registry={reference: record, receipt: tampered},
    )
    assert "calculation_expansion_mismatch" in resolution.problems
