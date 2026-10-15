"""Original cohort wording through socket HTTP, SQL, strict schemas and Redis replay."""

import gzip
import json

import pytest
from app.core.db import AsyncSessionLocal
from app.models.player import Player
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    assert_committed_replay,
    configure,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_record_availability_http import record_exchange
from app.tests.test_resolved_statistics_http import PrematureStatisticsClarification
from sqlalchemy import select


@pytest.mark.parametrize(
    "name,question,players,metric,opponent,window",
    [
        (
            "date004",
            "How did the Knicks perform from January 1 through January 31?",
            [],
            "record",
            None,
            "january",
        ),
        (
            "comparison002",
            "Compare Brunson and Towns as scorers this season.",
            ["Jalen Brunson", "Karl-Anthony Towns"],
            "points",
            None,
            None,
        ),
        (
            "comparison008",
            "Who had the better rebounding season, Towns or Hart?",
            ["Karl-Anthony Towns", "Josh Hart"],
            "rebounds",
            None,
            None,
        ),
        (
            "comparison015",
            "Compare Brunson's last 5 games with his season average.",
            ["Jalen Brunson"],
            "points",
            None,
            "last5-season",
        ),
        ("alias001", "How did NYK do vs BOS?", [], "record", "BOS", None),
        (
            "alias004",
            "Tell me about KAT vs the Raps.",
            ["Karl-Anthony Towns"],
            "points",
            "TOR",
            None,
        ),
        ("alias006", "How did they do v ATL?", [], "record", "ATL", None),
        (
            "alias008",
            "Did Mikal play well aginst Toronto?",
            ["Mikal Bridges"],
            "points",
            "TOR",
            None,
        ),
        ("alias009", "How did OG look vs the C's?", ["OG Anunoby"], "points", "BOS", None),
        (
            "performance-metric",
            "How did the Knicks perform in average points per game?",
            [],
            "points",
            None,
            None,
        ),
    ],
)
async def test_supported_original_wording_prepares_native_facts_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    players,
    metric,
    opponent,
    window,  # noqa: F811
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        identities = {
            player.full_name: player.id for player in (await db.execute(select(Player))).scalars()
        }
    adapter = PrematureStatisticsClarification("complete")
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, f"wording-{name}")
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = [game for game in raw["games"] if "NYK" in {game["home_team_id"], game["away_team_id"]}]
    if opponent:
        games = [game for game in games if opponent in {game["home_team_id"], game["away_team_id"]}]
    if window == "january":
        games = [game for game in games if game["game_date"][5:7] == "01"]
    if players:
        expected = []
        game_map = {game["nba_game_id"]: game for game in games}
        for name in players:
            player = next(player for player in raw["players"] if player["full_name"] == name)
            rows = sorted(
                [
                    row
                    for row in raw["player_game_stats"]
                    if row["nba_player_id"] == player["nba_player_id"]
                    and row["nba_game_id"] in game_map
                    and row["minutes"] > 0
                ],
                key=lambda row: (game_map[row["nba_game_id"]]["game_date"], row["nba_game_id"]),
            )
            populations = [rows[-5:], rows] if window == "last5-season" else [rows]
            for population in populations:
                expected.append(
                    {
                        "subject_id": f"player:{identities[name]}",
                        "metric_id": f"{metric}:average",
                        "sample_size": len(population),
                        "denominator": len(population),
                        "value": sum(row[metric] for row in population) / len(population),
                    }
                )
    elif metric == "record":
        wins = sum(
            (game["home_score"] > game["away_score"]) == (game["home_team_id"] == "NYK")
            for game in games
        )
        expected = [
            {"subject_id": "team:NYK", "metric_id": key, "sample_size": len(games), "value": value}
            for key, value in {"wins": wins, "losses": len(games) - wins}.items()
        ]
    else:
        expected = [
            {
                "subject_id": "team:NYK",
                "metric_id": "points:average",
                "sample_size": len(games),
                "denominator": len(games),
                "value": sum(
                    game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"]
                    for game in games
                )
                / len(games),
            }
        ]
    receipt["independent_expected_claims"] = expected
    save_receipt(tmp_path, record_property, f"wording-{receipt['request']['turn_id']}", receipt)
    assert_committed_replay(receipt)
    assert adapter.inputs[0]["user"]["schema"]["title"] == "ProposedAnswer"
    assert analyst_loop.payload_claims(adapter.inputs[0]["user"]), (
        "Supported native facts must precede clarification."
    )
    assert receipt["response"]["llm_validated"] is True
    claims = [
        citation["metadata"]["claim"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    ]
    for fact in expected:
        assert any(
            all(claim.get(key) == value for key, value in fact.items()) for claim in claims
        ), fact
    assert all(entry["schema_valid"] and entry["input_bytes"] <= 8000 for entry in adapter.inputs)
    assert settings.analyst_max_tool_rounds == 2 and settings.analyst_input_tokens == 8000


@pytest.mark.parametrize(
    "name,question",
    [
        ("turning001", "What was the Knicks' biggest scoring run against Boston?"),
        (
            "multiple-player-windows",
            "Compare Brunson and Towns average points in October versus January.",
        ),
    ],
)
async def test_unresolved_run_or_baseline_does_not_force_unrelated_total_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,  # noqa: F811
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = PrematureStatisticsClarification("complete")
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, f"wording-guard-{name}")
    save_receipt(tmp_path, record_property, f"wording-guard-{name}", receipt)
    assert_committed_replay(receipt)
    assert not receipt["response"]["citations"]
    if name == "turning001":
        assert receipt["response"]["route"] == "clarification"
        assert adapter.inputs == []
        assert receipt["capture"]["turn"]["model_calls"] == 0
    else:
        assert adapter.inputs[0]["user"]["schema"]["title"] == "Action"
        assert analyst_loop.payload_claims(adapter.inputs[0]["user"]) == []
