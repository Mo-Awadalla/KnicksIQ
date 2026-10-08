"""Observed model tool selections through HTTP, approved SQL and isolated Redis."""

import gzip
import json

import pytest
from app.core.db import AsyncSessionLocal
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    exchange,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA


class RecordAdapter(SyntheticAdapter):
    def __init__(self, tool, settings, behavior):
        super().__init__(tool)
        self.settings, self.behavior = settings, behavior

    async def generate(self, *, system, user):
        payload = json.loads(user)
        value = json.loads(await super().generate(system=system, user=user))
        if self.behavior == "capacity" and not payload["claims"]:
            self.settings.analyst_input_tokens = 4096
        if self.behavior == "omit":
            answer = (
                value.get("answer")
                if payload["schema"]["title"] == "Action"
                else value
                if payload["schema"]["title"] == "ProposedAnswer"
                else None
            )
            if answer is not None:
                wins = next(claim for claim in payload["claims"] if claim["metric_id"] == "wins")
                answer["text"] = wins["statement"]
                answer["claims"] = [
                    {"claim_id": wins["claim_id"], "displayed_value": wins["value"]}
                ]
        return json.dumps(value)


@pytest.mark.parametrize(
    "metric,question,month,behavior",
    [
        ("wins", "What was the Knicks record this season?", None, "complete"),
        ("losses", "What was the Knicks record in January?", "01", "complete"),
        ("wins", "What was the Knicks record this season?", None, "omit"),
        ("wins", "What was the Knicks record this season?", None, "capacity"),
    ],
)
async def test_advertised_record_metric_preserves_both_requested_counts(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    metric,
    question,
    month,
    behavior,
):
    settings = configure(monkeypatch)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = [
        game
        for game in raw["games"]
        if "NYK" in {game["home_team_id"], game["away_team_id"]}
        and (month is None or game["game_date"][5:7] == month)
    ]
    wins = sum(
        (game["home_score"] > game["away_score"])
        if game["home_team_id"] == "NYK"
        else (game["away_score"] > game["home_score"])
        for game in games
    )
    expected = {"wins": wins, "losses": len(games) - wins}
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    # Exact tool shape from the captured live response. The counter selector must
    # not narrow the user's paired record question to only wins or only losses.
    adapter = RecordAdapter(
        {"name": "get_team_stats", "question": question, "metric": metric, "aggregation": "total"},
        settings,
        behavior,
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    name = f"advertised-record-{metric}-{behavior}"
    receipt = await exchange(client, local_redis, adapter, name, question)
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"] is (behavior == "complete")
    claims = {
        citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    }
    assert set(claims) == set(expected)
    assert {name: claim["value"] for name, claim in claims.items()} == expected
    assert all(claim["sample_size"] == len(games) for claim in claims.values())
    assert all(claim["subject_id"] == "team:NYK" for claim in claims.values())
    for model_input in receipt["model_inputs"]:
        sent = {claim["metric_id"] for claim in model_input["user"]["claims"]}
        assert not sent or sent == {"wins", "losses"}


@pytest.mark.parametrize("metric", [None, "wins"])
async def test_team_record_comparison_uses_team_tool_without_player_metric_relaxation(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    metric,
):
    settings = configure(monkeypatch)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    expected = {}
    for month, label in (("01", "January"), ("02", "February")):
        games = [g for g in raw["games"] if g["game_date"][5:7] == month]
        wins = sum(
            (g["home_score"] > g["away_score"]) == (g["home_team_id"] == "NYK") for g in games
        )
        expected[label] = {"games": len(games), "wins": wins, "losses": len(games) - wins}
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    question = "Compare their January record with their February record."
    adapter = RecordAdapter(
        {"name": "get_team_stats", "question": question, "metric": metric},
        settings,
        "complete",
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(
        client, local_redis, adapter, f"team-record-comparison-{metric}", question
    )
    save_receipt(tmp_path, record_property, f"team-record-comparison-{metric}", receipt)
    assert_committed_replay(receipt)
    claims = [
        c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    ]
    assert {c["window"]["comparison_group"]: c["value"] for c in claims} == expected
    assert all(c["subject_id"] == "team:NYK" for c in claims)


@pytest.mark.parametrize("tool", ["get_player_stats", "compare_windows"])
async def test_team_only_metric_is_rejected_before_player_calculation(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    tool,
):
    configure(monkeypatch)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    brunson = next(player for player in raw["players"] if player["full_name"] == "Jalen Brunson")
    rows = [
        row
        for row in raw["player_game_stats"]
        if row["nba_player_id"] == brunson["nba_player_id"] and row["minutes"] > 0
    ]
    expected_points = sum(row["points"] for row in rows) / len(rows)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    question = "How many points did Jalen Brunson average?"
    adapter = SyntheticAdapter(
        {"name": tool, "question": question, "metric": "wins", "aggregation": "average"}
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"player-reject-{tool}", question)
    save_receipt(tmp_path, record_property, f"player-reject-{tool}", receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"] is False
    # Invalid typed player input must stop before another model round rather than
    # reach getattr(PlayerGameStat, 'wins') or manufacture team counters for a player.
    assert len(receipt["model_inputs"]) == 1
    claims = [
        citation["metadata"]["claim"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    ]
    assert {claim["metric_id"] for claim in claims} == {"points:average"}
    assert all(claim["value"] == pytest.approx(expected_points) for claim in claims)
    assert all(claim["sample_size"] == len(rows) for claim in claims)
