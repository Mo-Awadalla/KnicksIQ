"""Requested metrics and complete comparisons via real HTTP and approved SQL."""

import gzip
import json
import os
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from httpx import ASGITransport, AsyncClient


@pytest.mark.parametrize(
    "question,metric,players,comparison",
    [
        (
            "Who had the better rebounding season, Towns or Hart?",
            "rebounds",
            [1626157, 1628404],
            False,
        ),
        ("How many double-doubles did Towns have?", "double_doubles", [1626157], False),
        (
            "How many double doubles did Hart have in the regular season?",
            "double_doubles",
            [1628404],
            False,
        ),
        (
            "Compare Bridges' scoring before and after the All-Star break.",
            "points",
            [1628969],
            True,
        ),
        (
            "Compare Brunson's assists before and after the All-Star break in the regular season.",
            "assists",
            [1628973],
            True,
        ),
        ("What was Towns' rebounding average in January?", "rebounds", [1626157], False),
    ],
)
async def test_requested_metric_and_population(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    question,
    metric,
    players,
    comparison,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("Requested statistic proof cannot construct a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    source = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = {g["nba_game_id"]: g for g in source["games"]}
    names = {p["nba_player_id"]: p["full_name"] for p in source["players"]}
    expected = {}
    for player in players:
        rows = [
            r
            for r in source["player_game_stats"]
            if r["nba_player_id"] == player
            and r["team_id"] == "NYK"
            and r["minutes"] > 0
            and (
                "regular season" not in question
                or games[r["nba_game_id"]]["season_type"] == "regular"
            )
            and ("January" not in question or games[r["nba_game_id"]]["game_date"][5:7] == "01")
        ]
        if comparison:
            values = {}
            for label in ("before", "after"):
                population = [
                    r
                    for r in rows
                    if (games[r["nba_game_id"]]["game_date"] <= "2026-02-15") == (label == "before")
                ]
                values[label] = {
                    "value": sum(r[metric] for r in population) / len(population),
                    "count": len(population),
                }
            expected[names[player]] = values
        elif metric == "double_doubles":
            expected[names[player]] = sum(
                sum(r[k] >= 10 for k in ("points", "rebounds", "assists", "steals", "blocks")) >= 2
                for r in rows
            )
        else:
            expected[names[player]] = sum(r[metric] for r in rows) / len(rows)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    payload = {"question": question, "turn_id": "requested-player-stats-proof"}
    async with AsyncClient(
        transport=ASGITransport(client._transport.app, client=("192.0.2.201", 12345)),
        base_url="http://test",
    ) as http:
        with capture_turn() as capture:
            response = await http.post("/analysis/query", json=payload)
        replay = await http.post("/analysis/query", json=payload)
    body = response.json()
    receipt = {
        "request": payload,
        "http_status": response.status_code,
        "response": body,
        "replay": replay.json(),
        "capture": capture,
        "expected_from_raw_bundle": expected,
        "provider_attempts": attempts,
    }
    directory = Path(os.environ.get("KNICKSIQ_STATS_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    import hashlib

    with (directory / (hashlib.sha256(question.encode()).hexdigest()[:12] + ".json")).open(
        "x"
    ) as artifact:
        json.dump(receipt, artifact, indent=2)
    assert response.status_code == 200
    assert attempts == 0 and capture["turn"]["model_calls"] == 0
    assert replay.json() == body and body["state_committed"]
    claims = {
        c["metadata"]["claim"]["subject_id"]: c["metadata"]["claim"] for c in body["citations"]
    }
    assert len(claims) == len(players), body["answer"]
    for name, value in expected.items():
        claim = next(c for c in claims.values() if name in c["statement"])
        assert claim["metric_id"].split(":")[0] == metric
        if comparison:
            assert claim["value"]["before"] == pytest.approx(value["before"]["value"])
            assert claim["value"]["after"] == pytest.approx(value["after"]["value"])
            assert claim["window"]["before"]["sample_size"] == value["before"]["count"]
            assert claim["window"]["after"]["sample_size"] == value["after"]["count"]
            assert "before" in body["answer"].lower() and "after" in body["answer"].lower()
        else:
            assert claim["value"] == pytest.approx(value)
