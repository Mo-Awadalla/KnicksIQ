"""Release artifacts are reproducible, reconciled, and idempotent."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.dataset_release import DatasetRelease
from app.models.generated_stat_fact import GeneratedStatFact
from app.services.release_bundle import (
    ReleaseValidationError,
    build_bundle,
    load_release_bundle,
    read_bundle,
)
from basketball_core.analytics import FactCandidate, fact_fingerprint, score_fact_candidate
from sqlalchemy import func, select


def _payload() -> dict:
    return {
        "manifest": {
            "version": "2025-26.test.1",
            "season": "2025-26",
            "source": "test-fixture",
            "expected_games": 1,
            "expected_game_ids": ["test-release-game"],
        },
        "data": {
            "teams": [],
            "players": [],
            "games": [
                {
                    "nba_game_id": "test-release-game",
                    "season": "2025-26",
                    "game_date": "2026-01-01",
                    "home_team_id": "NYK",
                    "away_team_id": "BOS",
                    "home_score": 3,
                    "away_score": 2,
                    "status": "final",
                    "season_type": "regular",
                    "data_status": "analysis_ready",
                    "source_name": "nba_api",
                    "source_url": "https://stats.nba.com/stats/playbyplayv3?GameID=test-release-game",
                    "source_game_id": "test-release-game",
                    "source_fetched_at": "2026-01-02T00:00:00+00:00",
                    "source_payload_hash": "a" * 64,
                }
            ],
            "events": [
                {
                    "nba_game_id": "test-release-game",
                    "sequence": 1,
                    "period": 1,
                    "clock": "11:00",
                    "team_id": "NYK",
                    "nba_player_id": 1628973,
                    "event_type": "made_shot",
                    "description": "Brunson made a three",
                    "home_score": 3,
                    "away_score": 0,
                    "score_margin": 3,
                    "shot_type": "3pt",
                    "shot_result": "made",
                },
                {
                    "nba_game_id": "test-release-game",
                    "sequence": 2,
                    "period": 1,
                    "clock": "00:00",
                    "team_id": "BOS",
                    "nba_player_id": 1628369,
                    "event_type": "made_shot",
                    "description": "Boston made a two",
                    "home_score": 3,
                    "away_score": 2,
                    "score_margin": 1,
                    "shot_type": "2pt",
                    "shot_result": "made",
                },
            ],
            "period_scores": [
                {"nba_game_id": "test-release-game", "team_id": "NYK", "period": 1, "points": 3},
                {"nba_game_id": "test-release-game", "team_id": "BOS", "period": 1, "points": 2},
            ],
            "team_game_stats": [
                {"nba_game_id": "test-release-game", "team_id": "NYK", "points": 3},
                {"nba_game_id": "test-release-game", "team_id": "BOS", "points": 2},
            ],
            "player_game_stats": [
                {
                    "nba_game_id": "test-release-game",
                    "nba_player_id": 1628973,
                    "team_id": "NYK",
                    "points": 3,
                    "minutes": 12.0,
                    "starter": True,
                },
                {
                    "nba_game_id": "test-release-game",
                    "nba_player_id": 1628369,
                    "team_id": "BOS",
                    "points": 2,
                    "minutes": 12.0,
                    "starter": True,
                },
            ],
            "reports": [
                {
                    "nba_game_id": "test-release-game",
                    "report_type": "postgame",
                    "title": "Reviewed test report",
                    "summary": "NYK won 3-2.",
                    "reviewed": True,
                }
            ],
        },
    }


def test_bundle_is_deterministic_and_manifest_checked(tmp_path: Path) -> None:
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"
    assert build_bundle(_payload(), first) == build_bundle(_payload(), second)
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(ReleaseValidationError):
        read_bundle(first, "0" * 64)


async def test_loader_is_transactional_and_idempotent(db_session, tmp_path: Path) -> None:
    bundle = tmp_path / "release.json.gz"
    checksum = build_bundle(_payload(), bundle)
    first = await load_release_bundle(db_session, bundle, expected_sha256=checksum, activate=True)
    second = await load_release_bundle(db_session, bundle, expected_sha256=checksum, activate=True)
    assert first.inserted is True
    assert first.activated is True
    assert second.inserted is False
    assert (
        await db_session.execute(select(func.count()).select_from(DatasetRelease))
    ).scalar_one() == 1


async def test_loader_rejects_unreconciled_release(db_session, tmp_path: Path) -> None:
    payload = _payload()
    payload["data"]["period_scores"][0]["points"] = 1
    bundle = tmp_path / "invalid.json.gz"
    build_bundle(payload, bundle)
    with pytest.raises(ReleaseValidationError, match="do not reconcile"):
        await load_release_bundle(db_session, bundle)
    assert (
        await db_session.execute(select(func.count()).select_from(DatasetRelease))
    ).scalar_one() == 0


async def test_existing_staged_release_can_be_activated(db_session, tmp_path: Path) -> None:
    bundle = tmp_path / "release.json.gz"
    build_bundle(_payload(), bundle)
    staged = await load_release_bundle(db_session, bundle, activate=False)
    activated = await load_release_bundle(db_session, bundle, activate=True)
    assert staged.activated is False
    assert activated.inserted is False
    assert activated.activated is True


async def test_generated_facts_are_validated_hashed_and_loaded(db_session, tmp_path: Path) -> None:
    payload = _payload()
    payload["data"]["players"] = [
        {
            "nba_player_id": 1628973,
            "full_name": "Jalen Brunson",
            "team_id": "NYK",
            "position": "PG",
            "jersey_number": "11",
        }
    ]
    candidate = FactCandidate(
        fact_type="window_leader",
        player_ids=(1628973,),
        stat_keys=("points",),
        timeframe={"kind": "regular_season", "label": "regular season"},
        statement="Jalen Brunson led the window.",
        result={"value": 3.0, "rank": 1},
        source_game_ids=("test-release-game",),
        sample_size=1,
        components={
            name: 1.0
            for name in (
                "magnitude",
                "rarity",
                "sample_quality",
                "recency",
                "coverage",
                "basketball_relevance",
                "novelty",
                "interpretability",
            )
        },
    )
    total, components = score_fact_candidate(candidate)
    payload["data"]["generated_stat_facts"] = [
        {
            "fingerprint": fact_fingerprint(candidate),
            "fact_type": candidate.fact_type,
            "player_ids": list(candidate.player_ids),
            "stat_keys": list(candidate.stat_keys),
            "timeframe": candidate.timeframe,
            "statement": candidate.statement,
            "result": candidate.result,
            "source_game_ids": list(candidate.source_game_ids),
            "sample_size": candidate.sample_size,
            "total_score": total,
            "score_components": components,
            "detector_version": "player-intelligence-v1",
            "data_through": "2026-01-01",
        }
    ]
    bundle = tmp_path / "facts.json.gz"
    build_bundle(payload, bundle)
    await load_release_bundle(db_session, bundle)
    assert (
        await db_session.execute(select(func.count()).select_from(GeneratedStatFact))
    ).scalar_one() == 1

    payload["data"]["generated_stat_facts"][0]["fingerprint"] = "0" * 64
    invalid = tmp_path / "invalid-facts.json.gz"
    build_bundle(payload, invalid)
    with pytest.raises(ReleaseValidationError, match="fingerprint does not reconcile"):
        await load_release_bundle(db_session, invalid)
