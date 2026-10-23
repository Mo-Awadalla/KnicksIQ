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
from app.models.player import Player
from app.services import analyst_loop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Evidence
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_player_intelligence import _seed_release_stats
from jsonschema import Draft202012Validator
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
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "assertions": [
                            {
                                "text": span,
                                "assertion_type": "factual",
                                "verdict": "supported",
                                "offending_text": None,
                                "supporting_claim_ids": [
                                    c["claim_id"] for c in analyst_loop.payload_claims(payload)
                                ],
                                "supporting_evidence_ids": [],
                                "reason": "Exact backend statement in a synthetic protocol test.",
                            }
                            for span in payload["review_spans"]
                        ],
                        "follow_up_reviews": [],
                    },
                )
            )
        if not analyst_loop.payload_claims(payload):
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload, {"action": "call_tools", "tools": [self.tool], "answer": None}
                )
            )
        answer = {
            "text": " ".join(c["statement"] for c in analyst_loop.payload_claims(payload)),
            "claims": [
                {"claim_id": c["claim_id"], "displayed_value": c["value"], "decimal_places": None}
                for c in analyst_loop.payload_claims(payload)
            ],
            "evidence_ids": [],
            "fact_ids": [],
            "follow_up_questions": [],
        }
        if payload["schema"]["title"] == "ProposedAnswer":
            return json.dumps(analyst_loop.encode_model_response(payload, answer))
        return json.dumps(
            analyst_loop.encode_model_response(
                payload, {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
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
        retained_size = encoded_size(
            {
                key: payload[key]
                for key in (
                    "claim_context",
                    "statement_context",
                    "claims",
                    "claim_uses",
                    "evidence_context",
                    "evidence",
                )
                if key in payload
            }
        )
        assert retained_size <= settings.analyst_evidence_tokens


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
                    analyst_loop.encode_model_response(
                        payload,
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
                        },
                    )
                )
            if not analyst_loop.payload_claims(payload):
                return json.dumps(
                    analyst_loop.encode_model_response(
                        payload,
                        {
                            "action": "call_tools",
                            "tools": [{"name": tool, "question": question, "metric": "points"}],
                            "answer": None,
                        },
                    )
                )
            matched = {claim["metric_id"]: claim for claim in analyst_loop.payload_claims(payload)}
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
                analyst_loop.encode_model_response(
                    payload,
                    self.answer
                    if payload["schema"]["title"] == "ProposedAnswer"
                    else {
                        "action": "answer_from_available_evidence",
                        "tools": [],
                        "answer": self.answer,
                    },
                )
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


async def test_full_archive_record_reaches_independent_review_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    """The captured 201 draft shape must reach review with both whole populations."""
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        loaded = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.release_id == loaded.release_id)
                    .order_by(Game.game_date, Game.nba_game_id)
                )
            )
            .scalars()
            .all()
        )
    population = {game.id for game in games}
    wins = sum(
        (game.home_score > game.away_score) == (game.home_team_id == "NYK") for game in games
    )
    losses = len(games) - wins
    question = "What was the Knicks record this season?"
    text = (
        f"In the available 2025-26 archive, the Knicks went {wins}-{losses} across "
        f"{len(games)} archived games ({games[0].game_date} through "
        f"{games[-1].game_date}). This covers the archived regular-season and playoff "
        "games in the release, not necessarily the complete NBA season."
    )
    followups = [
        "What was the Knicks' home record in the 2025-26 archive?",
        "What was the Knicks' record in the 2025-26 playoffs?",
    ]

    class RecordAdapter(SyntheticAdapter):
        response_schema = None

        async def generate(self, *, system, user):
            payload = json.loads(user)
            actual_bytes = len((system + user).encode()) + encoded_size(self.response_schema)
            self.inputs.append({"system": system, "user": payload, "input_bytes": actual_bytes})
            assert actual_bytes <= 8000
            if payload["schema"]["title"] == "AnswerReview":
                assert "".join(payload["review_spans"]) == text
                assert payload["follow_up_questions"] == followups
                assert {
                    c["metric_id"]: c["value"] for c in analyst_loop.payload_claims(payload)
                } == {
                    "wins": wins,
                    "losses": losses,
                }
                assert all(
                    set(c["game_ids"]) == population for c in analyst_loop.payload_claims(payload)
                )
                return json.dumps(
                    analyst_loop.encode_model_response(
                        payload,
                        {
                            "assertions": [
                                {
                                    "text": span,
                                    "assertion_type": "factual",
                                    "verdict": "supported",
                                    "offending_text": None,
                                    "supporting_claim_ids": [
                                        c["claim_id"] for c in analyst_loop.payload_claims(payload)
                                    ],
                                    "supporting_evidence_ids": [],
                                    "reason": (
                                        "Independent SQL totals and complete archive population."
                                    ),
                                }
                                for span in payload["review_spans"]
                            ],
                            "follow_up_reviews": [
                                {
                                    "text": followup,
                                    "verdict": "insufficient_evidence",
                                    "reason": "These subsets were not independently queried.",
                                }
                                for followup in followups
                            ],
                        },
                    )
                )
            if not analyst_loop.payload_claims(payload):
                return json.dumps(
                    analyst_loop.encode_model_response(
                        payload, {"action": "call_tools", "tools": [self.tool], "answer": None}
                    )
                )
            by_metric = {c["metric_id"]: c for c in analyst_loop.payload_claims(payload)}
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "text": text,
                        "claims": [
                            {
                                "claim_id": by_metric[metric]["claim_id"],
                                "displayed_value": value,
                                "decimal_places": None,
                            }
                            for metric, value in (("wins", wins), ("losses", losses))
                        ],
                        "evidence_ids": [payload["evidence"][0]["evidence_id"]],
                        "fact_ids": [],
                        "follow_up_questions": followups,
                    },
                )
            )

    adapter = RecordAdapter(
        {"name": "get_team_stats", "question": question, "metric": "wins", "aggregation": "total"}
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, "full-archive-record", question)
    save_receipt(tmp_path, record_property, "full-archive-record", receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    assert receipt["response"]["answer"] == text
    assert receipt["response"]["follow_up_questions"] == []
    assert receipt["capture"]["turn"]["model_calls"] == 2
    assert [item["user"]["schema"]["title"] for item in adapter.inputs] == [
        "ProposedAnswer",
        "AnswerReview",
    ]
    delivered = {
        c["metadata"]["claim"]["metric_id"]: c["metadata"]["claim"]
        for c in receipt["response"]["citations"]
        if c["type"] == "verified_claim"
    }
    assert {metric: c["value"] for metric, c in delivered.items()} == {
        "wins": wins,
        "losses": losses,
    }
    assert all(set(c["game_ids"]) == population for c in delivered.values())
    assert all(c["sample_size"] == len(games) for c in delivered.values())


@pytest.mark.parametrize(
    "scenario", ["archive-points", "observed-double-doubles", "three-point-percentage", "starts"]
)
async def test_requested_scalar_survives_strict_planning_http(
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
        if scenario in {"three-point-percentage", "starts"}:
            release, _ = await _seed_release_stats(db)
            release_id = release.id
        else:
            loaded = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
            release_id = loaded.release_id
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.release_id == release_id)
                    .order_by(Game.game_date, Game.nba_game_id)
                )
            )
            .scalars()
            .all()
        )
        if scenario == "archive-points":
            assert len(games) == 101
            value = sum(
                game.home_score if game.home_team_id == "NYK" else game.away_score for game in games
            )
            population = {game.id for game in games}
            question = "How many total points did the Knicks score?"
            tool, metric, claim_metric = "get_team_stats", "points", "points"
        else:
            rows = (
                (
                    await db.execute(
                        select(PlayerGameStat)
                        .join(Player, Player.id == PlayerGameStat.player_id)
                        .where(
                            PlayerGameStat.release_id == release_id,
                            Player.full_name == "Karl-Anthony Towns",
                            PlayerGameStat.minutes > 0,
                        )
                        .order_by(PlayerGameStat.game_id)
                    )
                )
                .scalars()
                .all()
            )
            if scenario == "observed-double-doubles":
                # An absent archive row is unknown, not a zero or a reason to hide
                # the verified total over the remaining observed appearances.
                await db.delete(rows[-1])
                rows = rows[:-1]
                await db.commit()
            population = {row.game_id for row in rows}
            tool = "get_player_stats"
            if scenario == "observed-double-doubles":
                value = sum(
                    sum(
                        getattr(row, stat) >= 10
                        for stat in ("points", "rebounds", "assists", "steals", "blocks")
                    )
                    >= 2
                    for row in rows
                )
                question = "How many double-doubles did Karl-Anthony Towns have?"
                metric, claim_metric = "double_doubles", "double_doubles:total"
            elif scenario == "three-point-percentage":
                value = (
                    sum(row.three_pointers_made for row in rows)
                    / sum(row.three_pointers_attempted for row in rows)
                    * 100
                )
                question = "What was Karl-Anthony Towns' three-point percentage?"
                metric = claim_metric = "three_point_percentage"
            else:
                for index, row in enumerate(rows):
                    row.starter = index < 2
                await db.commit()
                value = 2
                question = "How many games did Karl-Anthony Towns start?"
                metric = claim_metric = "starts"
    text = f"The available archive shows {value} for the requested statistic."

    class ScalarAdapter:
        last_metadata = {"usage": {"cost": 0}, "provider": "synthetic-scalar-regression"}

        def __init__(self):
            self.inputs = []
            self.response_schema: dict[str, object] | None = None

        async def generate(self, *, system, user):
            payload = json.loads(user)
            assert self.response_schema is not None
            actual_bytes = len((system + user).encode()) + encoded_size(self.response_schema)
            self.inputs.append({"system": system, "user": payload, "input_bytes": actual_bytes})
            assert actual_bytes <= settings.analyst_input_tokens
            if payload["schema"]["title"] == "AnswerReview":
                response = {
                    "assertions": [
                        {
                            "text": text,
                            "assertion_type": "factual",
                            "verdict": "supported",
                            "offending_text": None,
                            "supporting_claim_ids": [
                                c["claim_id"] for c in analyst_loop.payload_claims(payload)
                            ],
                            "supporting_evidence_ids": [],
                            "reason": "Independent SQL value and complete population match.",
                        }
                    ],
                    "follow_up_reviews": [],
                }
            elif not analyst_loop.payload_claims(payload):
                if payload["results"]:
                    raise ValueError("The requested backend claim was dropped before drafting")
                response = {
                    "action": "call_tools",
                    "tools": [
                        {
                            "name": tool,
                            "question": question,
                            "metric": metric,
                            "aggregation": "total",
                        }
                    ],
                    "answer": None,
                }
            else:
                claim = next(
                    c
                    for c in analyst_loop.payload_claims(payload)
                    if c["metric_id"] == claim_metric
                )
                assert claim["value"] == value
                assert set(claim["game_ids"]) == population
                assert claim["sample_size"] == len(population)
                response = {
                    "text": text,
                    "claims": [
                        {
                            "claim_id": claim["claim_id"],
                            "displayed_value": value,
                            "decimal_places": None,
                        }
                    ],
                    "evidence_ids": [],
                    "fact_ids": [],
                    "follow_up_questions": [],
                }
                if payload["schema"]["title"] == "Action":
                    response = {
                        "action": "answer_from_available_evidence",
                        "tools": [],
                        "answer": response,
                    }
            Draft202012Validator(self.response_schema).validate(
                analyst_loop.encode_model_response(payload, response)
            )
            return json.dumps(analyst_loop.encode_model_response(payload, response))

    adapter = ScalarAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"requested-scalar-{scenario}", question)
    save_receipt(tmp_path, record_property, f"requested-scalar-{scenario}", receipt)
    assert receipt["response"]["llm_validated"], "The complete requested claim must reach review"
    assert_committed_replay(receipt)
    assert receipt["response"]["answer"] == text
    delivered = {
        citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    }
    assert delivered[claim_metric]["value"] == value
    assert set(delivered[claim_metric]["game_ids"]) == population
    assert delivered[claim_metric]["sample_size"] == len(population)


@pytest.mark.parametrize(
    ("requested_phase", "suggested_filter"),
    [
        (None, "in the 2025-26 regular season"),
        (None, "before January 1, 2026"),
        (None, "against Boston"),
        ("regular", "in the 2025-26 playoffs"),
    ],
)
async def test_player_aggregate_preserves_requested_population_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    requested_phase,
    suggested_filter,
):
    """A model's narrower investigation must not redefine the requested average."""
    configure(monkeypatch)
    question = "What was Karl-Anthony Towns' rebounding average?"
    if requested_phase:
        question = "What was Karl-Anthony Towns' regular-season rebounding average?"
    suggested_question = f"What was Karl-Anthony Towns' rebounding average {suggested_filter}?"
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        rows = list(
            (
                await db.execute(
                    select(PlayerGameStat, Game)
                    .join(Game, PlayerGameStat.game_id == Game.id)
                    .join(Player, PlayerGameStat.player_id == Player.id)
                    .where(
                        Player.full_name == "Karl-Anthony Towns",
                        PlayerGameStat.team_id == "NYK",
                        PlayerGameStat.minutes > 0,
                    )
                )
            ).all()
        )
    eligible = [
        (stat, game)
        for stat, game in rows
        if requested_phase is None or game.season_type == requested_phase
    ]
    expected_games = {game.id for _, game in eligible}
    expected_average = sum(stat.rebounds for stat, _ in eligible) / len(eligible)

    adapter = SyntheticAdapter(
        {
            "name": "get_player_stats",
            "question": suggested_question,
            "metric": "rebounds",
            "aggregation": "average",
        }
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    name = f"population-{requested_phase}-{suggested_filter.split()[0]}"
    receipt = await exchange(client, local_redis, adapter, name, question)
    receipt["independent_SQL_expectation"] = {
        "game_ids": sorted(expected_games),
        "sample_size": len(eligible),
        "rebounds_average": expected_average,
        "requested_phase": requested_phase,
    }
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"], "The requested full population must be answered"
    claims = [
        citation["metadata"]["claim"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    ]
    assert len(claims) == 1
    assert claims[0]["metric_id"] == "rebounds:average"
    assert set(claims[0]["game_ids"]) == expected_games
    assert claims[0]["sample_size"] == len(eligible)
    assert claims[0]["value"] == expected_average


@pytest.mark.parametrize("followups", [[], ["What was Towns' scoring average?"]])
async def test_complete_profile_lossless_strict_review_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    followups,
):
    """All four SQL facts and their immutable context reach the independent reviewer."""
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            (await db.execute(select(Game).where(Game.release_id == release.id).order_by(Game.id)))
            .scalars()
            .first()
        )
        assert game is not None
        towns = (
            await db.execute(select(Player).where(Player.full_name == "Karl-Anthony Towns"))
        ).scalar_one()
        stat = (
            await db.execute(
                select(PlayerGameStat).where(
                    PlayerGameStat.game_id == game.id,
                    PlayerGameStat.player_id == towns.id,
                )
            )
        ).scalar_one()
        game.game_date = date(2026, 1, 21)
        game.away_team_id = "BKN"
        game.home_score, game.away_score = 120, 66
        stat.points, stat.rebounds, stat.assists = 14, 8, 3
        await db.commit()
    question = "What did Towns do in the biggest win?"
    execute = AnalystTools.execute
    originals = {}
    original_sources = {}

    async def retain_native_context(self, call):
        result = await execute(self, call)
        if call.name == "get_player_stats":
            updated = []
            for claim in result.claims:
                filters = {
                    **claim.filters,
                    "nullable": None,
                    "boolean": False,
                    "zero": 0,
                    "empty_list": [],
                    "empty_object": {},
                }
                claim = claim.model_copy(update={"filters": filters})
                self.claims[claim.claim_id] = claim
                originals[claim.claim_id] = claim.model_dump(mode="json")
                updated.append(claim)
            result = result.model_copy(update={"claims": updated})
            for claim in result.claims:
                for ref in claim.supporting_evidence_ids:
                    original_sources[ref] = self.evidence[ref].model_dump(mode="json")
        return result

    monkeypatch.setattr(AnalystTools, "execute", retain_native_context)

    class CompleteProfileAdapter(SyntheticAdapter):
        response_schema: dict[str, object] | None = None

        async def generate(self, *, system, user):
            payload = json.loads(user)
            claims = analyst_loop.payload_claims(payload)
            actual_bytes = len((system + user).encode()) + encoded_size(self.response_schema)
            self.inputs.append(
                {
                    "system": system,
                    "user": payload,
                    "response_schema": self.response_schema,
                    "input_bytes": actual_bytes,
                    "restored_claims": claims,
                }
            )
            assert actual_bytes <= 8000
            if not claims:
                response = {"action": "call_tools", "tools": [self.tool], "answer": None}
            else:
                metrics = {claim["metric_id"]: claim["value"] for claim in claims}
                assert metrics == {
                    "points:total": 14,
                    "rebounds:total": 8,
                    "assists:total": 3,
                    "game_score": {"NYK": 120, "BKN": 66},
                }
                text = (
                    "Karl-Anthony Towns had 14 points, 8 rebounds and 3 assists in NYK's "
                    "120–66 win over BKN on 2026-01-21."
                )
                if payload["schema"]["title"] == "AnswerReview":
                    assert "".join(payload["review_spans"]) == text
                    assert payload["follow_up_questions"] == followups
                    response = {
                        "assertions": [
                            {
                                "text": span,
                                "assertion_type": "factual",
                                "verdict": "supported",
                                "offending_text": None,
                                "supporting_claim_ids": [claim["claim_id"] for claim in claims],
                                "supporting_evidence_ids": [],
                                "reason": "All requested SQL facts retain their exact scope.",
                            }
                            for span in payload["review_spans"]
                        ],
                        "follow_up_reviews": [
                            {
                                "text": suggestion,
                                "verdict": "insufficient_evidence",
                                "reason": "The average was not queried.",
                            }
                            for suggestion in followups
                        ],
                    }
                else:
                    answer = {
                        "text": text,
                        "claims": [
                            {
                                "claim_id": claim["claim_id"],
                                "displayed_value": claim["value"],
                                "decimal_places": None,
                            }
                            for claim in claims
                        ],
                        "evidence_ids": [],
                        "fact_ids": [],
                        "follow_up_questions": followups,
                    }
                    response = answer
                    if payload["schema"]["title"] == "Action":
                        response = {
                            "action": "answer_from_available_evidence",
                            "tools": [],
                            "answer": answer,
                        }
            assert self.response_schema is not None
            Draft202012Validator(self.response_schema).validate(
                analyst_loop.encode_model_response(payload, response)
            )
            return json.dumps(analyst_loop.encode_model_response(payload, response))

    adapter = CompleteProfileAdapter({"name": "get_player_stats", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    name = f"complete-profile-{len(followups)}-followups"
    receipt = await exchange(client, local_redis, adapter, name, question)
    receipt["native_claims"] = originals
    receipt["native_sources"] = original_sources
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    delivered = {
        citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]["value"]
        for citation in receipt["response"]["citations"]
        if citation["type"] == "verified_claim"
    }
    assert delivered == {
        "points:total": 14,
        "rebounds:total": 8,
        "assists:total": 3,
        "game_score": {"NYK": 120, "BKN": 66},
    }
    for citation in receipt["response"]["citations"]:
        if citation["type"] != "verified_claim":
            continue
        filters = citation["metadata"]["claim"]["filters"]
        if "nullable" not in filters:
            continue
        assert filters["nullable"] is None
        assert filters["boolean"] is False
        assert type(filters["zero"]) is int and filters["zero"] == 0
        assert filters["empty_list"] == []
        assert filters["empty_object"] == {}
