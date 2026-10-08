"""Evidence packaging through HTTP/SQL/Redis, retaining exact protocol artifacts."""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.services import analyst_loop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Evidence
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_player_intelligence import _seed_release_stats
from sqlalchemy import select


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def configure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    monkeypatch.setattr(settings, "analyst_input_tokens", 8000)
    monkeypatch.setattr(settings, "analyst_evidence_tokens", 6000)
    return settings


async def exchange(client, redis, adapter, name, question):
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.125")
    payload = {
        "question": question,
        "turn_id": f"payload-regression-{name}",
        "expected_revision": 0,
    }
    with capture_turn() as first:
        response = await client.post("/analysis/query", json=payload)
    calls_before_replay = len(adapter.inputs)
    with capture_turn() as replay_capture:
        replay = await client.post("/analysis/query", json=payload)
    return {
        "artifact_version": "analyst-payload-http-v1",
        "request": payload,
        "status": response.status_code,
        "response": response.json(),
        "capture": first,
        "replay_status": replay.status_code,
        "replay": replay.json(),
        "replay_capture": replay_capture,
        "model_inputs": adapter.inputs,
        "calls_before_replay": calls_before_replay,
        "calls_after_replay": len(adapter.inputs),
        "budget_before": "0.125",
        "budget_after": (await redis.get(key)).decode(),
        "real_provider_requests": 0,
    }


def save_receipt(tmp_path, record_property, name, receipt):
    directory = Path(os.environ.get("KNICKSIQ_PAYLOAD_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{name}.json"
    with destination.open("x") as file:
        json.dump(receipt, file, indent=2)
    record_property("payload_artifact", str(destination))


def assert_committed_replay(receipt):
    assert receipt["status"] == receipt["replay_status"] == 200
    assert receipt["response"]["state_committed"]
    assert receipt["response"] == receipt["replay"]
    assert receipt["calls_before_replay"] == receipt["calls_after_replay"]
    assert receipt["replay_capture"] == {
        "searches": [],
        "tools": [],
        "turn": {"replayed": True, "model_calls": 0},
    }
    assert receipt["budget_before"] == receipt["budget_after"]


class SyntheticAdapter:
    """Protocol-only responses: exact backend values, with a real review round."""

    last_metadata = {"usage": {"cost": 0}, "provider": "synthetic-payload-regression"}

    def __init__(self, tool):
        self.tool = tool
        self.inputs = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        self.inputs.append(
            {"system": system, "user": payload, "input_bytes": len((system + user).encode())}
        )
        if payload["schema"]["title"] == "AnswerReview":
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": span,
                            "assertion_type": "factual",
                            "verdict": "supported",
                            "offending_text": None,
                            "supporting_claim_ids": [c["claim_id"] for c in payload["claims"]],
                            "supporting_evidence_ids": [],
                            "reason": "Exact backend statement in a synthetic protocol test.",
                        }
                        for span in payload["review_spans"]
                    ],
                    "follow_up_reviews": [],
                }
            )
        if not payload["claims"]:
            return json.dumps({"action": "call_tools", "tools": [self.tool], "answer": None})
        answer = {
            "text": " ".join(c["statement"] for c in payload["claims"]),
            "claims": [
                {"claim_id": c["claim_id"], "displayed_value": c["value"]}
                for c in payload["claims"]
            ],
            "evidence_ids": [],
            "fact_ids": [],
            "follow_up_questions": [],
        }
        if payload["schema"]["title"] == "ProposedAnswer":
            return json.dumps(answer)
        return json.dumps(
            {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
        )


async def test_current_discovery_survives_oversized_result_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        release, player = await _seed_release_stats(db)
        # Four appearances produce a compact, real aggregate receipt, leaving
        # room for canonical discovery beside an oversized tool source.
        for day in (4, 5):
            game = Game(
                release_id=release.id,
                nba_game_id=f"payload-{day}",
                season=release.season,
                game_date=date(2026, 1, day),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=110,
                away_score=100,
                status="final",
                season_type="regular",
                source_name="test",
            )
            db.add(game)
            await db.flush()
            db.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=player.id,
                    team_id="NYK",
                    minutes=30,
                    points=day * 10,
                )
            )
        await db.commit()
        source_rows = (
            await db.execute(
                select(Game, PlayerGameStat)
                .join(PlayerGameStat, PlayerGameStat.game_id == Game.id)
                .where(
                    Game.release_id == release.id,
                    PlayerGameStat.player_id == player.id,
                )
            )
        ).all()
        game_dates = {game.id: str(game.game_date) for game, _ in source_rows}
        appearance_game_ids = {game.id for game, stat in source_rows if stat.minutes > 0}
    question = "Brunson's average against Boston?"
    adapter = SyntheticAdapter(
        {"name": "get_player_stats", "question": question, "metric": "points"}
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    execute = AnalystTools.execute
    seam = {}

    async def result_with_oversized_record(self, call):
        result = await execute(self, call)
        if call.name != "get_player_stats":
            return result
        # Real SQL discovery is left intact. Reproduce a whole oversized source
        # and a duplicate result/discovery identity at the tool boundary.
        assert self.discovery and self.discovery.evidence
        compact = min(
            (
                item
                for item in self.discovery.evidence
                if item.game_id in game_dates
                and item.metadata.get("date") == game_dates[item.game_id]
            ),
            key=lambda item: encoded_size(item.model_dump(mode="json")),
        )
        oversized = compact.model_copy(
            update={"evidence_id": "synthetic:oversized-current-result", "text": "x" * 9000}
        )
        unrelated = Evidence(
            evidence_id="synthetic:unrelated-prior-game",
            release_id=self.release.version,
            game_id=999999,
            text="Unrelated source hydrated from an earlier turn.",
        )
        self.evidence[oversized.evidence_id] = oversized
        self.evidence[unrelated.evidence_id] = unrelated
        seam.update(
            discovery=[e.model_dump(mode="json") for e in self.discovery.evidence],
            compact_id=compact.evidence_id,
            oversized=oversized.model_dump(mode="json"),
            unrelated=unrelated.model_dump(mode="json"),
            claims=[c.model_dump(mode="json") for c in result.claims],
            supporting_evidence={
                ref: self.evidence[ref].model_dump(mode="json")
                for claim in result.claims
                for ref in claim.supporting_evidence_ids
            },
        )
        return result.model_copy(update={"evidence": [oversized, compact, compact]})

    monkeypatch.setattr(AnalystTools, "execute", result_with_oversized_record)
    receipt = await exchange(client, local_redis, adapter, "source-union", question)
    receipt["controlled_tool_result"] = seam
    save_receipt(tmp_path, record_property, "source-union", receipt)
    assert_committed_replay(receipt)
    body = receipt["response"]
    assert body["llm_validated"]
    assert body["route"] == "llm_analyst"
    assert not body["refused"]
    assert body["data_version"] == release.version
    searches = [
        search
        for search in receipt["capture"]["searches"]
        if search["purpose"] == "canonical_discovery"
        and search["status"] == "ok"
        and search["release"] == release.version
    ]
    assert searches
    assert seam["compact_id"] in {
        identity for search in searches for identity in search["candidate_evidence_ids"]
    }
    support_ids = set(seam["supporting_evidence"])
    delivered_claims = {
        citation["metadata"]["claim"]["claim_id"]: citation["metadata"]["claim"]
        for citation in body["citations"]
    }
    assert {
        (claim["subject_id"], claim["metric_id"]): claim["value"]
        for claim in delivered_claims.values()
    } == {(f"player:{player.id}", "points:average"): 35.0}
    for claim in delivered_claims.values():
        assert claim["release_id"] == release.version
        assert claim["season"] == release.season
        assert claim["filters"]["opponent_id"] == "BOS"
        assert set(claim["game_ids"]) == appearance_game_ids
        assert claim["sample_size"] == claim["denominator"] == 4
        assert claim["window"] == {
            "date_start": "2026-01-01",
            "date_end": "2026-01-05",
        }
    for citation in body["citations"]:
        assert citation["type"] == "verified_claim"
        assert citation["metadata"]["evidence_id"] in support_ids
    for request in adapter.inputs:
        assert request["input_bytes"] <= settings.analyst_input_tokens
        payload = request["user"]
        retained_size = (
            sum(encoded_size([c]) for c in payload["claims"])
            + sum(encoded_size(e) for e in payload["evidence"])
            + sum(encoded_size([use]) for use in payload.get("claim_uses", []))
        )
        assert retained_size <= settings.analyst_evidence_tokens


async def test_oversized_boston_narrative_falls_back_before_dispatch_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    question = "What was the key sequence in the Boston loss?"
    adapter = SyntheticAdapter({"name": "search_archive", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, "oversized-boston", question)
    receipt["bundle"] = {"path": str(BUNDLE), "sha256": SHA}
    save_receipt(tmp_path, record_property, "oversized-boston", receipt)
    assert_committed_replay(receipt)
    body = receipt["response"]
    assert not body["llm_validated"]
    claim = next(
        c["metadata"]["claim"]
        for c in body["citations"]
        if c["type"] == "verified_claim"
        and c["metadata"]["claim"]["metric_id"] == "canonical_game_narrative"
    )
    assert claim["value"]["games"][0]["nba_game_id"] == "0022500320"
    runs = claim["value"]["runs"]
    assert [(r["points"], r["start_sequence"], r["end_sequence"]) for r in runs] == [
        (12, 128, 146),
        (12, 282, 299),
    ]
    assert [[e["sequence"] for e in r["scoring_events"]] for r in runs] == [
        [128, 131, 137, 140, 144, 146],
        [282, 290, 293, 295, 299],
    ]
    assert "2025-12-02" in body["answer"]
    assert all(
        r["start_clock"] in body["answer"] and r["end_clock"] in body["answer"] for r in runs
    )
    assert receipt["calls_before_replay"] == receipt["capture"]["turn"]["model_calls"] == 0, (
        "A required narrative that cannot fit must fall back before provider dispatch"
    )


@pytest.mark.parametrize("scenario", ["appearance-average", "team-record", "team-leader"])
async def test_strict_format_bounded_complete_population_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    scenario,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        release, player = await _seed_release_stats(db)
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.release_id == release.id)
                    .order_by(Game.game_date, Game.nba_game_id)
                )
            )
            .scalars()
            .all()
        )
        # The two players tie across all three games, although Brunson misses
        # the middle game. Neither a single-game leader nor a partial record
        # answers the requested population.
        rows = (
            (
                await db.execute(
                    select(PlayerGameStat).where(
                        PlayerGameStat.release_id == release.id,
                        PlayerGameStat.player_id == player.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.minutes > 0:
                row.points = 21 if row.game_id == games[0].id else 30
        await db.commit()
    scenarios = {
        "appearance-average": (
            "What was Brunson's scoring average over his last 2 appearances?",
            "get_player_stats",
            {"points:average": 25.5},
            {row.game_id for row in rows if row.minutes > 0},
            "Jalen Brunson averaged 25.5 points over his last 2 appearances.",
        ),
        "team-record": (
            "What was the Knicks record over their last 3 games?",
            "get_team_stats",
            {"wins": 3, "losses": 0},
            {game.id for game in games},
            "The Knicks had 3 wins and 0 losses over their last 3 games.",
        ),
        "team-leader": (
            "Who led the Knicks in scoring over their last 3 games?",
            "get_team_stats",
            {
                "points:leaders": {
                    "leaders": ["Jalen Brunson", "Karl-Anthony Towns"],
                    "total": 51,
                }
            },
            {game.id for game in games},
            "Jalen Brunson and Karl-Anthony Towns tied for the Knicks scoring lead "
            "with 51 points each over their last 3 games.",
        ),
    }
    question, tool, values, population, text = scenarios[scenario]

    class StrictBoundaryAdapter:
        """Fixed expected SQL answers, not an echo of the packaged claims."""

        last_metadata = {"usage": {"cost": 0}, "provider": "synthetic-strict-boundary"}

        def __init__(self):
            self.inputs = []
            self.response_schema = None
            self.answer = None

        async def generate(self, *, system, user):
            payload = json.loads(user)
            actual_bytes = len((system + user).encode()) + encoded_size(self.response_schema)
            self.inputs.append({"system": system, "user": payload, "input_bytes": actual_bytes})
            if actual_bytes > settings.analyst_input_tokens:
                raise ValueError("Actual strict provider input exceeds the unchanged bound")
            if payload["schema"]["title"] == "AnswerReview":
                assert self.answer is not None, "Answer review requires a generated answer"
                return json.dumps(
                    {
                        "assertions": [
                            {
                                "text": text,
                                "assertion_type": "factual",
                                "verdict": "supported",
                                "offending_text": None,
                                "supporting_claim_ids": [
                                    use["claim_id"] for use in self.answer["claims"]
                                ],
                                "supporting_evidence_ids": [],
                                "reason": "The requested SQL population supports these values.",
                            }
                        ],
                        "follow_up_reviews": [],
                    }
                )
            if not payload["claims"]:
                return json.dumps(
                    {
                        "action": "call_tools",
                        "tools": [{"name": tool, "question": question, "metric": "points"}],
                        "answer": None,
                    }
                )
            matched = {claim["metric_id"]: claim for claim in payload["claims"]}
            if not values.keys() <= matched.keys():
                raise ValueError("A requested statistic was omitted")
            if any(set(matched[metric]["game_ids"]) != population for metric in values):
                raise ValueError("A requested population was truncated")
            self.answer = {
                "text": text,
                "claims": [
                    {
                        "claim_id": matched[metric]["claim_id"],
                        "displayed_value": value,
                        "decimal_places": None,
                    }
                    for metric, value in values.items()
                ],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            return json.dumps(
                self.answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {
                    "action": "answer_from_available_evidence",
                    "tools": [],
                    "answer": self.answer,
                }
            )

    adapter = StrictBoundaryAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"strict-{scenario}", question)
    save_receipt(tmp_path, record_property, f"strict-{scenario}", receipt)
    assert_committed_replay(receipt)
    body = receipt["response"]
    assert body["llm_validated"], "A complete bounded strict-format answer must reach review"
    assert body["route"] == "llm_analyst"
    assert body["answer"] == text
    delivered = {
        citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]
        for citation in body["citations"]
    }
    assert {metric: claim["value"] for metric, claim in delivered.items()} == values
    assert all(set(claim["game_ids"]) == population for claim in delivered.values())
    assert all(claim["sample_size"] == len(population) for claim in delivered.values())
    assert all(claim["release_id"] == release.version for claim in delivered.values())
    assert adapter.inputs and adapter.inputs[-1]["user"]["schema"]["title"] == "AnswerReview"
    assert all(request["input_bytes"] <= 8000 for request in adapter.inputs)
