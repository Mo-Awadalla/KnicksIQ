"""Record availability through loopback HTTP, SQL and isolated Redis; written first.

Failure modes are recorded in record-availability-failure-modes.md. The scripted
provider never requests tools: absent evidence reproduces the live premature
clarification, and deliberate omissions must recover a complete factual record.
"""

import gzip
import json
import os
from datetime import UTC, datetime

import httpx
import pytest
from app.core.db import AsyncSessionLocal
from app.evaluation.guarded_load import private_server
from app.evaluation.trace_capture import capture_turn
from app.models.game import Game
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from sqlalchemy import select


class PrematureRecordClarification(SyntheticAdapter):
    def __init__(self, behavior):
        super().__init__({})
        self.behavior = behavior

    async def generate(self, *, system, user):
        payload = json.loads(user)
        claims = analyst_loop.payload_claims(payload)
        if claims and self.behavior == "complete":
            return await super().generate(system=system, user=user)
        self.inputs.append({"system": system, "user": payload})
        selected = [claim for claim in claims if claim["metric_id"] == self.behavior]
        if payload["schema"]["title"] == "AnswerReview":
            value = {
                "assertions": [
                    {
                        "text": span,
                        "assertion_type": "factual" if selected else "coverage",
                        "verdict": "supported",
                        "offending_text": None,
                        "supporting_claim_ids": [claim["claim_id"] for claim in selected],
                        "supporting_evidence_ids": [],
                        "reason": "Scripted record availability regression.",
                    }
                    for span in payload["review_spans"]
                ],
                "follow_up_reviews": [],
            }
        else:
            answer = {
                "text": " ".join(claim["statement"] for claim in selected)
                or "Which Knicks team and season type do you mean?",
                "claims": [
                    {"claim_id": claim["claim_id"], "displayed_value": claim["value"]}
                    for claim in selected
                ],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            value = (
                answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
        return json.dumps(analyst_loop.encode_model_response(payload, value))


async def record_exchange(client, redis, adapter, question, name):
    captures = []

    async def captured_app(scope, receive, send):
        with capture_turn() as capture:
            await client._transport.app(scope, receive, send)
        captures.append(capture)

    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.125")
    payload = {
        "question": question,
        "turn_id": f"record-regression-{name}",
        "expected_revision": 0,
    }
    async with private_server(captured_app, lifespan="off") as base_url:
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
            response = await http.post("/analysis/query", json=payload)
            calls_before_replay = len(adapter.inputs)
            replay = await http.post("/analysis/query", json=payload)
    return {
        "artifact_version": "record-availability-socket-http-v1",
        "transport": "loopback TCP HTTP (Uvicorn)",
        "database": "SQL release loaded from SHA256-pinned archive",
        "archive_sha256": SHA,
        "request": payload,
        "status": response.status_code,
        "response": response.json(),
        "capture": captures[0],
        "replay_status": replay.status_code,
        "replay": replay.json(),
        "replay_capture": captures[1],
        "model_inputs": adapter.inputs,
        "calls_before_replay": calls_before_replay,
        "calls_after_replay": len(adapter.inputs),
        "budget_before": "0.125",
        "budget_after": (await redis.get(key)).decode(),
        "real_provider_requests": 0,
    }


@pytest.mark.parametrize(
    "name,question,population,behavior",
    [
        ("frozen-001", "What was the Knicks record this season?", "all", "complete"),
        ("shorthand", "What is the Knicks record?", "all", "complete"),
        ("omit-both", "What is the Knicks record?", "all", "omit"),
        ("omit-losses", "What is the Knicks record?", "all", "wins"),
        ("omit-wins", "What is the Knicks record?", "all", "losses"),
        ("regular", "What was the Knicks regular season record?", "regular", "complete"),
        ("playoffs", "What was the Knicks playoff record?", "playoffs", "complete"),
        ("january", "What was the Knicks record in January?", "january", "complete"),
        ("opponent", "What was the Knicks record against Boston?", "boston", "complete"),
        ("last-ten", "What was the Knicks record in the last 10 games?", "last-ten", "complete"),
    ],
)
async def test_available_record_precedes_model_clarification_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    population,
    behavior,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        game_ids = {
            game.nba_game_id: game.id for game in (await db.execute(select(Game))).scalars()
        }
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = sorted(
        [
            game
            for game in raw["games"]
            if "NYK" in {game["home_team_id"], game["away_team_id"]}
            and game["status"] == "final"
            and game["home_score"] != game["away_score"]
        ],
        key=lambda game: (game["game_date"], game["nba_game_id"]),
    )
    if population in {"regular", "playoffs"}:
        games = [game for game in games if game["season_type"] == population]
    elif population == "january":
        games = [game for game in games if game["game_date"][5:7] == "01"]
    elif population == "boston":
        games = [game for game in games if "BOS" in {game["home_team_id"], game["away_team_id"]}]
    elif population == "last-ten":
        games = games[-10:]
    wins = sum(
        (game["home_score"] > game["away_score"]) == (game["home_team_id"] == "NYK")
        for game in games
    )
    expected = {"wins": wins, "losses": len(games) - wins}
    expected_ids = {game_ids[game["nba_game_id"]] for game in games}
    adapter = PrematureRecordClarification(behavior)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, name)
    receipt["expected"] = {"values": expected, "game_ids": sorted(expected_ids)}
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    if os.environ.get("KNICKSIQ_APPROVED_BUNDLE") and population == "all":
        assert expected == {"wins": 69, "losses": 32} and len(expected_ids) == 101
    assert adapter.inputs, "A valid prepared record must be presented to the writer"
    first_claims = analyst_loop.payload_claims(adapter.inputs[0]["user"])
    assert {claim["metric_id"] for claim in first_claims} == {"wins", "losses"}, (
        "Available record must be calculated before the writer can prematurely clarify"
    )
    body = receipt["response"]
    assert body["llm_validated"] is (behavior == "complete")
    claims = {
        citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]
        for citation in body["citations"]
        if citation["type"] == "verified_claim"
    }
    assert {metric: claim["value"] for metric, claim in claims.items()} == expected
    assert all(claim["subject_id"] == "team:NYK" for claim in claims.values())
    assert all(set(claim["game_ids"]) == expected_ids for claim in claims.values())
    assert all(claim["sample_size"] == len(games) for claim in claims.values())
    assert "Which Knicks team" not in body["answer"]


@pytest.mark.parametrize(
    "name,question",
    [
        ("unavailable-season", "What was the Knicks record in 2024-25?"),
        ("unresolved-player", "What was his record?"),
        ("player-record", "What was Jalen Brunson's record?"),
    ],
)
async def test_unresolved_or_player_record_never_substitutes_team_record_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = PrematureRecordClarification("complete")
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, name)
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    assert not any(
        citation.get("metadata", {}).get("claim", {}).get("subject_id") == "team:NYK"
        for citation in receipt["response"]["citations"]
    )
    assert not any(
        claim["metric_id"] in {"wins", "losses"}
        for model_input in adapter.inputs
        for claim in analyst_loop.payload_claims(model_input["user"])
    )
