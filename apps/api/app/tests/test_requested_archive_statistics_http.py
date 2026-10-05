"""Explicit statistics through HTTP, independently calculated from raw archive."""

import gzip
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from httpx import ASGITransport, AsyncClient


async def test_requested_archive_statistics(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("No provider is authorized for statistic regression")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = sorted(raw["games"], key=lambda g: (g["game_date"], g["nba_game_id"]))
    by_id = {g["nba_game_id"]: g for g in games}

    def own(g):
        return g["home_score"] if g["home_team_id"] == "NYK" else g["away_score"]

    def allowed(g):
        return g["away_score"] if g["home_team_id"] == "NYK" else g["home_score"]

    requests = []

    def team(question, metric, population, value):
        requests.append((question, metric, population, value, None))

    team(
        "What was the Knicks average score per game?",
        "points:average",
        games,
        sum(map(own, games)) / len(games),
    )
    team(
        "What was the Knicks average margin?",
        "margin:average",
        games,
        sum(own(g) - allowed(g) for g in games) / len(games),
    )
    team(
        "How many points per game did the Knicks allow?",
        "points_allowed:average",
        games,
        sum(map(allowed, games)) / len(games),
    )
    team(
        "How many games did the Knicks score at least 120?",
        "games:count",
        games,
        sum(own(g) >= 120 for g in games),
    )
    team(
        "How many games did the Knicks hold opponents under 100?",
        "games:count",
        games,
        sum(allowed(g) < 100 for g in games),
    )
    for question, metric, population, value in [
        (
            "How many points did the Knicks average in their last 10 games?",
            "points:average",
            games[-10:],
            sum(map(own, games[-10:])) / 10,
        ),
        (
            "What was their average margin over the last 8 games?",
            "margin:average",
            games[-8:],
            sum(own(g) - allowed(g) for g in games[-8:]) / 8,
        ),
        (
            "What was the defense like over the last 5 games by points allowed?",
            "points_allowed:average",
            games[-5:],
            sum(map(allowed, games[-5:])) / 5,
        ),
        (
            "What was their record in the first 10 games?",
            "wins",
            games[:10],
            sum(own(g) > allowed(g) for g in games[:10]),
        ),
    ]:
        team(question, metric, population, value)
    regular = [g for g in games if g["season_type"] == "regular"][-15:]
    team(
        "What was their record over the final 15 regular-season games?",
        "wins",
        regular,
        sum(own(g) > allowed(g) for g in regular),
    )
    for question, metric, nba_id, aggregation in [
        ("How many total points did Jalen Brunson score?", "points:total", 1628973, "total"),
        (
            "What was Mikal Bridges' three-point percentage?",
            "three_point_percentage",
            1628969,
            "pct",
        ),
        ("How many games did Josh Hart start?", "starts", 1628404, "starts"),
        ("Did Mikal play well aginst Toronto?", "points:average", 1628969, "average"),
        (
            "How many points did Hart average in his last 5 games?",
            "points:average",
            1628404,
            "average",
        ),
    ]:
        rows = [
            s
            for s in raw["player_game_stats"]
            if s["nba_player_id"] == nba_id
            and s["team_id"] == "NYK"
            and s["minutes"] > 0
            and (
                "Toronto" not in question
                or "TOR"
                in {
                    by_id[s["nba_game_id"]]["home_team_id"],
                    by_id[s["nba_game_id"]]["away_team_id"],
                }
            )
        ]
        if "last 5" in question:
            rows = sorted(
                rows, key=lambda s: (by_id[s["nba_game_id"]]["game_date"], s["nba_game_id"])
            )[-5:]
        value = (
            sum(s["points"] for s in rows)
            if aggregation == "total"
            else sum(s["three_pointers_made"] for s in rows)
            / sum(s["three_pointers_attempted"] for s in rows)
            * 100
            if aggregation == "pct"
            else sum(bool(s["starter"]) for s in rows)
            if aggregation == "starts"
            else sum(s["points"] for s in rows) / len(rows)
        )
        requests.append((question, metric, [by_id[s["nba_game_id"]] for s in rows], value, nba_id))
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    directory = Path(os.environ.get("KNICKSIQ_ARCHIVE_STATS_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=False) if not directory.exists() else None
    failures = []
    for index, (question, metric, population, value, player) in enumerate(requests):
        payload = {"question": question, "turn_id": f"requested-archive-statistic-{index}"}
        async with AsyncClient(
            transport=ASGITransport(client._transport.app, client=(f"192.0.2.{index + 1}", 12345)),
            base_url="http://test",
        ) as http:
            with capture_turn() as capture:
                response = await http.post("/analysis/query", json=payload)
            replay = await http.post("/analysis/query", json=payload)
        result = response.json()
        claims = {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"]
            for c in result.get("citations", [])
            if c.get("type") == "verified_claim"
        }
        matched = [c for c in claims.values() if c["metric_id"] == metric]
        receipt = {
            "request": payload,
            "response": result,
            "replay": replay.json(),
            "capture": capture,
            "expected_metric": metric,
            "expected_value": value,
            "expected_nba_games": sorted(g["nba_game_id"] for g in population),
            "expected_player_nba_id": player,
            "provider_attempts": attempts,
        }
        with (directory / f"case-{index:02}.json").open("x") as artifact:
            json.dump(receipt, artifact, indent=2)
        if response.status_code != 200 or replay.json() != result or not matched:
            failures.append((index, "missing claim or failed request", result.get("answer")))
            continue
        claim = matched[0]
        wrong_value = abs(claim["value"] - value) > 0.00001
        if wrong_value or claim["sample_size"] != len(population):
            failures.append((index, "wrong value/population", claim))
        if player and claim["window"] != {
            "date_start": min(g["game_date"] for g in population),
            "date_end": max(g["game_date"] for g in population),
        }:
            failures.append((index, "wrong observed appearance window", claim["window"]))
        state = capture["turn"]["committed_evidence_proposal"]
        evidence = {e["evidence_id"]: e for e in state["evidence"]}
        source_refs = []
        for ref in claim["supporting_evidence_ids"]:
            source_refs.extend(evidence[ref]["metadata"].get("source_evidence_ids", [ref]))
        if len(source_refs) != len(population):
            failures.append((index, "incomplete underlying receipts", len(source_refs)))
    with (directory / "summary.json").open("x") as artifact:
        json.dump(
            {
                "cases": len(requests),
                "failures": failures,
                "provider_attempts": attempts,
                "gold_approved": False,
            },
            artifact,
            indent=2,
        )
    assert attempts == 0
    assert not failures, failures
