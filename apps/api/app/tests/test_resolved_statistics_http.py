"""Native quantitative preparation through socket HTTP, SQL and isolated Redis."""

import gzip
import json
from collections import Counter

import pytest
from app.core.db import AsyncSessionLocal
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
from app.tests.test_record_availability_http import record_exchange
from jsonschema import Draft202012Validator, ValidationError


class PrematureStatisticsClarification(SyntheticAdapter):
    response_schema: dict | None = None

    def __init__(self, behavior):
        super().__init__({})
        self.behavior = behavior

    def record_wire(self, raw, system, user):
        schema = self.response_schema
        assert schema is not None
        entry = self.inputs[-1]
        entry.update(
            schema=schema,
            raw_response=raw,
            input_bytes=len((system + user).encode()) + len(analyst_loop.encoded(schema).encode()),
        )
        try:
            Draft202012Validator(schema).validate(json.loads(raw))
            entry["schema_valid"] = True
        except ValidationError:
            entry["schema_valid"] = False
        if self.behavior == "complete" or not analyst_loop.payload_claims(entry["user"]):
            assert entry["schema_valid"]
        return raw

    async def generate(self, *, system, user):
        payload = json.loads(user)
        claims = analyst_loop.payload_claims(payload)
        if claims and self.behavior == "complete":
            raw = await super().generate(system=system, user=user)
            return self.record_wire(raw, system, user)
        self.inputs.append({"system": system, "user": payload, "schema": self.response_schema})
        if payload["schema"]["title"] == "AnswerReview":
            value = {
                "assertions": [
                    {
                        "text": span,
                        "assertion_type": "conversational",
                        "verdict": "supported",
                        "offending_text": None,
                        "supporting_claim_ids": [],
                        "supporting_evidence_ids": [],
                        "reason": "Scripted model repeats the fresh002 premature clarification.",
                    }
                    for span in payload["review_spans"]
                ],
                "follow_up_reviews": [],
            }
        else:
            answer = {
                "text": "I can look that up, but please specify the game or date range.",
                "claims": [],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            value = (
                answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
        wire = analyst_loop.encode_model_response(payload, value)
        # Deliberately omitted mandatory facts may be schema-invalid; they must
        # recover through the real native fallback, never a mocked validator.
        if not claims:
            assert self.response_schema is not None
            Draft202012Validator(self.response_schema).validate(wire)
        return self.record_wire(json.dumps(wire), system, user)


@pytest.mark.parametrize(
    "name,question,subject,metric,behavior",
    [
        ("frozen002", "How many total points did the Knicks score?", "team", "points", "complete"),
        (
            "team-average",
            "What was the Knicks average points per game?",
            "team",
            "points:average",
            "complete",
        ),
        (
            "frozen003",
            "What was the Knicks average score per game?",
            "team",
            "points:average",
            "complete",
        ),
        (
            "omit-score-average",
            "What was the Knicks average score per game?",
            "team",
            "points:average",
            "omit",
        ),
        (
            "score-january",
            "What was the Knicks average score per game in January?",
            "team",
            "points:average",
            "complete",
        ),
        ("team-wins", "How many games did the Knicks win?", "team", "wins", "complete"),
        ("team-games", "How many games did the Knicks play?", "team", "games:count", "complete"),
        (
            "player-total",
            "What were Jalen Brunson's total points?",
            "player",
            "points:total",
            "complete",
        ),
        (
            "omit-team-total",
            "How many total points did the Knicks score?",
            "team",
            "points",
            "omit",
        ),
        (
            "omit-player-total",
            "What were Jalen Brunson's total points?",
            "player",
            "points:total",
            "omit",
        ),
    ],
)
async def test_resolved_statistics_precede_model_clarification_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    subject,
    metric,
    behavior,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = PrematureStatisticsClarification(behavior)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, f"native-stat-{name}")
    save_receipt(tmp_path, record_property, f"native-stat-{name}", receipt)
    assert_committed_replay(receipt)
    first = adapter.inputs[0]["user"]
    assert first["schema"]["title"] == "ProposedAnswer"
    assert analyst_loop.payload_claims(first), (
        "Resolved native statistics must exist before writing."
    )
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = [g for g in raw["games"] if "NYK" in {g["home_team_id"], g["away_team_id"]}]
    if name == "score-january":
        games = [game for game in games if game["game_date"][5:7] == "01"]
    points = sum(g["home_score"] if g["home_team_id"] == "NYK" else g["away_score"] for g in games)
    if subject == "player":
        player = next(p for p in raw["players"] if p["full_name"] == "Jalen Brunson")
        rows = [
            s
            for s in raw["player_game_stats"]
            if s["nba_player_id"] == player["nba_player_id"] and s["minutes"] > 0
        ]
        expected, sample = sum(s["points"] for s in rows), len(rows)
    else:
        sample = len(games)
        expected = (
            points / sample
            if metric == "points:average"
            else points
            if metric == "points"
            else sum(
                (g["home_score"] > g["away_score"]) == (g["home_team_id"] == "NYK") for g in games
            )
            if metric == "wins"
            else sample
        )
        if metric == "wins":
            # The resolver scopes this wording to wins; count and population
            # both come from independently checking the raw archived scores.
            sample = expected
    claims = [
        c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    ]
    assert any(
        c["metric_id"] == metric and c["value"] == expected and c["sample_size"] == sample
        for c in claims
    )
    assert "specify" not in receipt["response"]["answer"].lower()
    assert receipt["response"]["llm_validated"] is (behavior == "complete")
    assert settings.analyst_input_tokens == 8000 and settings.analyst_max_tool_rounds == 2
    assert all(entry["input_bytes"] <= 8000 for entry in adapter.inputs)


@pytest.mark.parametrize(
    "name,question",
    [
        ("ambiguous", "What were Smith's total points?"),
        ("unavailable", "What were the Knicks total points in 2024-25?"),
        ("unsupported-team", "What were the Knicks total rebounds?"),
        ("unsupported-credit-score", "What was the Knicks average credit score?"),
        ("unspecified-player-aggregation", "How many points did Jalen Brunson score?"),
        ("arbitrary-comparison", "Compare Jalen Brunson's average points in October with January."),
        (
            "team-all-star-comparison",
            "Compare Knicks average points before and after the All-Star break.",
        ),
        (
            "comparison-noun",
            "A comparison of Jalen Brunson's average points in October and January.",
        ),
        (
            "comparison-better",
            "Was Jalen Brunson's average scoring better in October or January?",
        ),
        ("grouped-rebounds", "Compare Knicks average rebounds at home and away."),
        (
            "period-month-comparison",
            "Compare Knicks average points in the first quarter in October versus January.",
        ),
        ("total-points-allowed", "What were the Knicks total points allowed?"),
        ("grouped-total-points", "Compare Knicks total points at home and away."),
        ("grouped-total-turnovers", "Compare Knicks total turnovers in October and January."),
        (
            "comparison-difference",
            "What is the difference between Jalen Brunson's average points in October and January?",
        ),
        (
            "comparison-differ",
            "How did Jalen Brunson's average points differ between October and January?",
        ),
        ("discovery", "Give me interesting Knicks scoring facts."),
    ],
)
async def test_non_native_or_unresolved_statistics_keep_planning_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    if name == "ambiguous":
        raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
        active = {row["nba_player_id"] for row in raw["player_game_stats"]}
        surnames = Counter(
            player["full_name"].split()[-1]
            for player in raw["players"]
            if player["nba_player_id"] in active
        )
        surname = next(name for name, count in sorted(surnames.items()) if count > 1)
        question = f"What were {surname}'s total points?"
    adapter = PrematureStatisticsClarification("complete")
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await record_exchange(client, local_redis, adapter, question, f"native-guard-{name}")
    save_receipt(tmp_path, record_property, f"native-guard-{name}", receipt)
    assert_committed_replay(receipt)
    if name == "ambiguous":
        assert adapter.inputs == []
        assert receipt["capture"]["turn"]["model_calls"] == 0
        assert receipt["response"]["route"] == "clarification"
    else:
        assert adapter.inputs[0]["user"]["schema"]["title"] == "Action"
        assert analyst_loop.payload_claims(adapter.inputs[0]["user"]) == []
    assert not receipt["response"]["citations"]
