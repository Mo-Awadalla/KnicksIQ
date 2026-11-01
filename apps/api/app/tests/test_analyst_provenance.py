"""Private SQL provenance: actual row snapshots, computed digests and verified content.

Written before ``app/services/analyst_provenance.py``. The cases drive the real
analyst tools over seeded release rows and the real evaluation verifier, so a
claimed hash never stands in for content that was actually produced and checked.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from app.evaluation.mapping import load_documents, load_mapping
from app.evaluation.observations import EvidenceRecord, canonical_digest
from app.evaluation.scoring_cases import _content_problem
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_provenance import (
    GAME_FIELDS,
    PLAYER_GAME_STAT_FIELDS,
    ProvenanceCapture,
    game_projection,
    player_stat_projection,
)
from app.services.analyst_provenance import (
    canonical_digest as provenance_digest,
)
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Evidence, ToolCall
from sqlalchemy import select

VERSION = "2025-26.provenance-test"


def calculation_reference(*, subject: str, metric: str, sources: list[str], value: float) -> str:
    """The recipe ``app.evaluation.mapping`` recomputes."""
    body = json.dumps([VERSION, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(body.encode()).hexdigest()


ARCHIVE = (
    ("2025-11-05", "NYK", "BOS", 112, 104),
    ("2025-11-20", "BOS", "NYK", 100, 108),
    ("2025-12-05", "NYK", "BOS", 118, 110),
    ("2025-12-15", "BOS", "NYK", 120, 99),
    ("2025-12-31", "SAS", "NYK", 134, 132),
    ("2026-01-02", "NYK", "ATL", 99, 111),
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


def test_projection_digest_uses_the_actual_row_values() -> None:
    game = SimpleNamespace(
        away_score=111,
        away_team_id="BOS",
        data_status="analysis_ready",
        game_date=date(2025, 10, 22),
        game_label=None,
        home_score=119,
        home_team_id="NYK",
        nba_game_id="0022500003",
        season="2025-26",
        season_type="regular",
        series_game_number=None,
        series_name=None,
        source_fetched_at=datetime.fromisoformat("2026-07-02T17:34:48.243949+00:00"),
        source_game_id="0022500003",
        source_name="NbaApiDataSource",
        source_payload_hash="1d0190811246218c975f0d38c29e533504888475e6fd25349d48b8723eb88b8d",
        source_url="https://stats.nba.com/stats/playbyplayv3?GameID=0022500003",
        status="final",
    )
    projection = game_projection(game)
    assert projection["game_date"] == "2025-10-22"
    assert projection["source_fetched_at"] == "2026-07-02T17:34:48.243949+00:00"
    digest = provenance_digest(projection)
    assert digest == canonical_digest(projection)
    game.home_score = 120
    assert provenance_digest(game_projection(game)) != digest


def test_capture_records_the_sql_identity_and_computed_hash() -> None:
    capture = ProvenanceCapture(enabled=True)
    game = SimpleNamespace(**{field: None for field in GAME_FIELDS})
    game.nba_game_id = "0022500003"
    game.game_date = date(2025, 10, 22)
    game.id = 41
    projection = game_projection(game)
    evidence = Evidence(
        evidence_id=f"{VERSION}:game:41",
        release_id=VERSION,
        game_id=41,
        text="row",
        metadata={"date": "2025-10-22"},
    )
    assert capture.capture_row(
        evidence.evidence_id,
        collection="games",
        canonical_id="game:0022500003",
        row=projection,
        source_row_id=41,
    )
    (entry,) = capture.registry([evidence.model_dump(mode="json")])
    assert entry["source_row_id"] == 41
    assert entry["sequence_id"] is None
    assert entry["source_collection"] == "games"
    assert entry["source_row"] == projection
    assert entry["row_sha256"] == provenance_digest(projection)
    # The model-facing metadata stays exactly as it was: no snapshot is smuggled in.
    assert entry["metadata"] == {"date": "2025-10-22"}


async def test_loop_exposes_the_private_registry_and_keeps_state_round_trip_safe(
    db_session,
) -> None:
    tools = await _tools(db_session, "What was the Knicks record this season?")
    loop = AnalystLoop(tools, [])
    loop.request_id = "provenance-test"
    result = await loop.run(allow_model=False)
    assert result["evidence"]
    by_id = {item["evidence_id"]: item for item in result["evidence"]}
    for item in result["evidence"]:
        if item["evidence_id"].startswith("calculation:"):
            # A calculation record describes an expansion; it is not itself a SQL row.
            assert "source_row" not in item
            continue
        game = next(game for game in tools.games if game.id == item["game_id"])
        assert item["source_row"] == game_projection(game)
        assert item["row_sha256"] == provenance_digest(item["source_row"])
        assert item["source_row_id"] == game.id
    assert any(item.get("row_sha256") for item in result["evidence"])
    # Committed state stays plain evidence so a later turn can revalidate it.
    for raw in result["state"]["evidence"]:
        assert "source_row" not in raw
        assert Evidence.model_validate(raw).evidence_id in by_id


async def test_player_average_calculation_records_the_actual_numerator(db_session) -> None:
    tools = await _tools(db_session, "How many points per game did Brunson average?")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question="How many points per game did Brunson average?",
            metric="points",
            aggregation="average",
        )
    )
    (claim,) = result.claims
    expected_total = sum(stat.points for stat, _ in tools.rows)
    assert claim.value == expected_total / len(tools.rows)
    assert claim.denominator == len(tools.rows)
    (receipt,) = [tools.evidence[ref] for ref in claim.supporting_evidence_ids]
    assert receipt.evidence_id.startswith("calculation:")
    assert receipt.metadata["numerator"] == expected_total
    assert receipt.metadata["denominator"] == len(tools.rows)
    assert receipt.metadata["sample_size"] == len(tools.rows)
    assert len(receipt.metadata["source_evidence_ids"]) == len(tools.rows)
    sources = [tools.evidence[ref] for ref in receipt.metadata["source_evidence_ids"]]
    entries = tools.provenance.registry([item.model_dump(mode="json") for item in sources])
    assert len(entries) == len(tools.rows)
    stat_ids = {stat.id for stat, _ in tools.rows}
    for entry in entries:
        assert entry["source_collection"] == "player_game_stats"
        assert entry["source_row"]["nba_player_id"] == 1628973
        assert entry["source_row_id"] in stat_ids
        assert entry["row_sha256"] == provenance_digest(entry["source_row"])


def _mapping(tmp_path: Path, rows: dict[str, dict], version: str = VERSION):
    payload = {
        "scope": "test mapping",
        "version": version,
        "release_id": 1,
        "bundle_sha256": "e" * 64,
        "verified_source_references": 0,
        "rows": rows,
        "players": {"1628384": {"id": 77, "name": "Jalen Brunson"}},
    }
    path = tmp_path / "runtime-mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_mapping(path)


def _row_entry(projection: dict, row_id: int, game_id: int) -> dict:
    return {
        "collection": "games",
        "row_sha256": provenance_digest(projection),
        "database_row_id": row_id,
        "game_id": game_id,
        "release_id": 1,
        "runtime_receipt": f"{VERSION}:game:{game_id}",
        "player_id": None,
    }


def _projection(home_score: int = 119) -> dict:
    game = SimpleNamespace(**{field: None for field in GAME_FIELDS})
    game.nba_game_id = "0022500003"
    game.home_score = home_score
    game.away_score = 111
    game.home_team_id = "NYK"
    game.away_team_id = "BOS"
    game.status = "final"
    return game_projection(game)


def _source_record(receipt: str, projection: dict) -> EvidenceRecord:
    return EvidenceRecord.from_dict(
        {
            "evidence_id": receipt,
            "release_id": VERSION,
            "text": "row",
            "source_row": projection,
            "row_sha256": provenance_digest(projection),
        }
    )


def test_evaluator_accepts_only_content_that_matches_its_computed_hash(tmp_path: Path) -> None:
    projection = _projection()
    mapping = _mapping(tmp_path, {"game:0022500003": _row_entry(projection, 1, 12)})
    reference = f"{VERSION}:game:12"
    claim = None

    verified = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "row",
            "game_id": 12,
            "source_row_id": 1,
            "source_row": projection,
            "metadata": {"row_sha256": provenance_digest(projection)},
        }
    )
    resolution = mapping.resolve_citation(reference, claim)
    assert _content_problem(reference, resolution, mapping, {reference: verified}) is None

    tampered = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "row",
            "game_id": 12,
            "source_row_id": 1,
            "source_row": _projection(home_score=120),
            "metadata": {"row_sha256": provenance_digest(projection)},
        }
    )
    assert (
        _content_problem(reference, resolution, mapping, {reference: tampered})
        == "citation_content_mismatch"
    )

    claimed_only = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "row",
            "game_id": 12,
            "source_row_id": 1,
            "metadata": {"row_sha256": provenance_digest(projection)},
        }
    )
    assert (
        _content_problem(reference, resolution, mapping, {reference: claimed_only})
        == "citation_content_unverified"
    )


def test_evaluator_rejects_a_calculation_sample_beyond_its_expansion(tmp_path: Path) -> None:
    projection = _projection()
    rows = {"game:0022500003": _row_entry(projection, 1, 12)}
    mapping = _mapping(tmp_path, rows)
    sources = [f"{VERSION}:game:12"]
    value = 119.0
    reference = calculation_reference(
        subject="team:NYK", metric="points", sources=sources, value=value
    )
    claim = {
        "subject_id": "team:NYK",
        "metric_id": "points",
        "value": value,
        "denominator": None,
        "sample_size": 4,
    }
    record = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "calc",
            "metadata": {
                "source_evidence_ids": sources,
                "calculation_version": "analyst-v1",
                "sample_size": 4,
                "denominator": None,
            },
        }
    )
    resolution = mapping.resolve_citation(
        reference,
        claim,
        registry={reference: record, sources[0]: _source_record(sources[0], projection)},
    )
    assert resolution.problems == ("calculation_population_mismatch",)


def test_evaluator_rejects_numerator_inconsistent_with_value(tmp_path: Path) -> None:
    projection = _projection()
    mapping = _mapping(tmp_path, {"game:0022500003": _row_entry(projection, 1, 12)})
    sources = [f"{VERSION}:game:12"]
    value = 119.0
    reference = calculation_reference(
        subject="team:NYK", metric="points_per_game", sources=sources, value=value
    )
    claim = {
        "subject_id": "team:NYK",
        "metric_id": "points_per_game",
        "value": value,
        "denominator": 1.0,
        "sample_size": 1,
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
                "numerator": 118.0,
            },
        }
    )
    resolution = mapping.resolve_citation(
        reference,
        claim,
        registry={reference: record, sources[0]: _source_record(sources[0], projection)},
    )
    assert resolution.problems == ("calculation_arithmetic_mismatch",)


def test_player_stat_projection_uses_relational_nba_ids() -> None:
    game = SimpleNamespace(nba_game_id="0022500003")
    player = SimpleNamespace(nba_player_id=1628384)
    stat = SimpleNamespace(**{field: 0 for field in PLAYER_GAME_STAT_FIELDS})
    stat.minutes = 37.5
    stat.team_id = "NYK"
    stat.starter = True
    stat.position = "G"
    projection = player_stat_projection(game, stat, player)
    assert projection["nba_game_id"] == "0022500003"
    assert projection["nba_player_id"] == 1628384
    assert set(projection) == set(PLAYER_GAME_STAT_FIELDS)


def test_evaluator_requires_a_document_payload_snapshot(tmp_path: Path) -> None:
    projection = _projection()
    mapping = _mapping(tmp_path, {"game:0022500003": _row_entry(projection, 1, 12)})
    payload = {"game_id": 12, "chunk_id": "game:12:poss:3", "semantic_summary": "text"}
    documents = tmp_path / "runtime-document-mapping.json"
    documents.write_text(
        json.dumps(
            {
                "version": VERSION,
                "scope": "test documents",
                "documents": {
                    f"{VERSION}:game:12:poss:3": {
                        "runtime_evidence_id": f"{VERSION}:game:12:poss:3",
                        "collection": "knicks_possessions",
                        "game_id": 12,
                        "point_id": "00000000-0000-0000-0000-000000000001",
                        "payload_sha256": provenance_digest(payload),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    mapping = load_documents(documents, mapping)
    resolution = mapping.resolve_document("game:12:poss:3")
    reference = f"{VERSION}:game:12:poss:3"
    assert resolution.resolved

    verified = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "chunk",
            "payload": payload,
            "metadata": {"payload_sha256": provenance_digest(payload)},
        }
    )
    assert _content_problem(reference, resolution, mapping, {reference: verified}) is None
    claimed_only = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "chunk",
            "metadata": {"payload_sha256": provenance_digest(payload)},
        }
    )
    assert (
        _content_problem(reference, resolution, mapping, {reference: claimed_only})
        == "citation_content_unverified"
    )
    tampered = EvidenceRecord.from_dict(
        {
            "evidence_id": reference,
            "release_id": VERSION,
            "text": "chunk",
            "payload": {**payload, "semantic_summary": "changed"},
            "metadata": {"payload_sha256": provenance_digest(payload)},
        }
    )
    assert (
        _content_problem(reference, resolution, mapping, {reference: tampered})
        == "citation_content_mismatch"
    )
