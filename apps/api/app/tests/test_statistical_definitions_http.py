"""Count boundaries and ambiguity choices use the actual archived population."""

import gzip
import json
import os
import re
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from sqlalchemy import select


async def test_score_predicates_and_archived_date_choices_over_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "require_active_release", True)
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = [g for g in raw["games"] if "NYK" in {g["home_team_id"], g["away_team_id"]}]
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        game_ids = {g.nba_game_id: g.id for g in (await db.execute(select(Game))).scalars()}
    directory = Path(os.environ.get("KNICKSIQ_DEFINITIONS_ARTIFACT_DIR", str(tmp_path)))
    record_property("statistical_definition_artifacts", str(directory))

    knicks_scores = [
        g["home_score"] if g["home_team_id"] == "NYK" else g["away_score"] for g in games
    ]
    opponent_scores = [
        g["away_score"] if g["home_team_id"] == "NYK" else g["home_score"] for g in games
    ]
    cutoff = knicks_scores[0]
    cases = [
        (
            "inclusive-boundary",
            f"How many games did the Knicks score at least {cutoff} points?",
            knicks_scores,
            ">=",
            cutoff,
        ),
        (
            "exclusive-boundary",
            f"How many games did the Knicks score over {cutoff} points?",
            knicks_scores,
            ">",
            cutoff,
        ),
        (
            "frozen-scored",
            "How many games did the Knicks score at least 120 points?",
            knicks_scores,
            ">=",
            120,
        ),
        (
            "frozen-allowed",
            "How many games did the Knicks hold opponents under 100 points?",
            opponent_scores,
            "<",
            100,
        ),
    ]
    observed = {}
    for name, question, scores, operator, value in cases:
        expected = sum(
            s >= value if operator == ">=" else s > value if operator == ">" else s < value
            for s in scores
        )
        body, _ = await request(client, local_redis, monkeypatch, directory, name, question)
        claims = {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"] for c in body["citations"]
        }
        assert len(claims) == 1
        claim = next(iter(claims.values()))
        assert claim["metric_id"] == "games:count" and claim["value"] == expected
        assert claim["sample_size"] == len(games)
        assert claim["eligibility"]["score_predicate"] == {
            "subject_id": "opponent" if name == "frozen-allowed" else "team:NYK",
            "metric_id": "points",
            "operator": operator,
            "cutoff": value,
        }
        observed[name] = claim["value"]
    assert observed["inclusive-boundary"] > observed["exclusive-boundary"]

    body, _ = await request(
        client,
        local_redis,
        monkeypatch,
        directory,
        "paired-record",
        "How many wins and losses did the Knicks have?",
    )
    record_games = [
        g for g in games if g["status"] == "final" and g["home_score"] != g["away_score"]
    ]
    wins = sum(
        (g["home_score"] > g["away_score"])
        if g["home_team_id"] == "NYK"
        else (g["away_score"] > g["home_score"])
        for g in record_games
    )
    record_claims = {
        c["metadata"]["claim"]["metric_id"]: c["metadata"]["claim"]
        for c in body["citations"]
        if c["type"] == "verified_claim"
    }
    assert set(record_claims) == {"wins", "losses"}
    for metric, expected in {"wins": wins, "losses": len(record_games) - wins}.items():
        claim = record_claims[metric]
        assert claim["value"] == expected
        assert claim["subject_id"] == "team:NYK"
        assert claim["sample_size"] == len(record_games)
        assert set(claim["game_ids"]) == {game_ids[g["nba_game_id"]] for g in record_games}
        assert claim["statement"] in body["answer"]

    dates = {g["game_date"] for g in games if "BOS" in {g["home_team_id"], g["away_team_id"]}}
    assert len(dates) > 1
    body, capture = await request(
        client,
        local_redis,
        monkeypatch,
        directory,
        "boston-choices",
        "Which Boston game do you mean?",
    )
    assert body["route"] == "clarification" and not body["citations"]
    assert not capture["turn"]["delivered_state"].get("claims")
    assert set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", body["answer"])) == dates
    with (directory / "summary.json").open("x") as handle:
        json.dump(
            {"cases": 5, "bundle_sha256": SHA, "counts": observed, "boston_dates": sorted(dates)},
            handle,
            indent=2,
        )
