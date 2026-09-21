"""Adversarial evidence, actual Redis races and bounded orchestration contracts."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.services import analyst_budget, analyst_loop, analyst_sessions
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_sessions import SessionConflict, SessionTurn
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import (
    AnswerReview,
    AssertionReview,
    ClaimUse,
    ProposedAnswer,
    ToolCall,
    validate_review,
    validate_structure,
)
from app.tests.test_player_intelligence import _seed_release_stats
from redis.asyncio import Redis


@pytest.fixture
async def local_redis(monkeypatch, tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server is required for atomic concurrency integration tests")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            binary,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def connection():
        return Redis.from_url(f"redis://127.0.0.1:{port}", socket_timeout=1)

    redis = await connection()
    try:
        for _ in range(100):
            try:
                await redis.ping()
                break
            except ConnectionError:
                await asyncio.sleep(0.01)
            except Exception:
                await asyncio.sleep(0.01)
        for module in (analyst_budget, analyst_sessions):
            monkeypatch.setattr(module, "_redis", connection)
        yield redis
    finally:
        await redis.aclose()
        process.terminate()
        process.wait(timeout=5)


async def test_session_race_replay_conflict_and_atomic_commit(local_redis):
    turn_id = "first-turn-identity"
    first = await SessionTurn.begin(None, turn_id, 0, {"question": "stat"})
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, "second-turn-identity", 0, {"question": "stat"})
    assert await first.commit({"answer": "Committed"}, {"delivered_fact_ids": ["fact:1"]})
    replay = await SessionTurn.begin(None, turn_id, 0, {"question": "stat"})
    assert replay.replay == {"answer": "Committed"}
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, turn_id, 0, {"question": "changed"})
    with pytest.raises(SessionConflict):
        await SessionTurn.begin(first.token, "new-turn-identity", 0, {"question": "stat"})
    next_turn = await SessionTurn.begin(first.token, "new-turn-identity", 1, {"question": "stat"})
    assert next_turn.state["delivered_fact_ids"] == ["fact:1"]
    await local_redis.delete(next_turn.key + ":lease")
    assert not await next_turn.commit({"answer": "Lost lease"}, {"delivered_fact_ids": ["bad"]})
    assert json.loads(await local_redis.hget(first.key, "state"))["delivered_fact_ids"] == [
        "fact:1"
    ]
    assert 86000 < await local_redis.ttl(first.key) <= 86400


async def test_atomic_budget_never_resets_missing_ledger(local_redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_monthly_cutoff_usd", 0.08)
    assert await BudgetReservation.reserve(0.02) is None
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, 0)
    attempts = await asyncio.gather(*[BudgetReservation.reserve(0.02) for _ in range(12)])
    accepted = [r for r in attempts if r is not None]
    assert len(accepted) == 4
    assert float(await local_redis.get(key)) == pytest.approx(0.08)
    await accepted[0].settle(None)
    assert float(await local_redis.get(key)) == pytest.approx(0.08)
    await accepted[0].settle(0.005)
    await accepted[0].settle(0)
    assert float(await local_redis.get(key)) == pytest.approx(0.065)
    await local_redis.delete(key)
    assert await BudgetReservation.reserve(0.001) is None


async def make_tools(db, question="Give me an interesting stat", state=None):
    release, player = await _seed_release_stats(db)
    tools = AnalystTools(db, release, question, release.season, state or {})
    await tools.prepare()
    return tools, player


async def test_populations_and_scope_cannot_be_changed_by_model(db_session):
    tools, player = await make_tools(db_session, "Brunson regular season points")
    result = await tools.execute(ToolCall(name="get_player_stats", question="Towns playoffs"))
    assert result.status == "ok"
    claim = result.claims[0]
    assert claim.subject_id == f"player:{player.id}"
    assert claim.value == 25 and claim.denominator == 2 and claim.sample_size == 2
    assert claim.season_type == "regular"
    assert claim.game_ids is not None
    assert len(claim.game_ids) == 2
    answer = ProposedAnswer(
        text=claim.statement, claims=[ClaimUse(claim_id=claim.claim_id, displayed_value=25)]
    )
    assert validate_structure(answer, tools.claims, tools.evidence, {}, tools.release.version)
    wrong = answer.model_copy(
        update={"claims": [ClaimUse(claim_id=claim.claim_id, displayed_value=-25)]}
    )
    assert not validate_structure(wrong, tools.claims, tools.evidence, {}, tools.release.version)
    assert not validate_structure(answer, tools.claims, tools.evidence, {}, "other-release")


async def test_discovery_novelty_phase_and_complete_claim_records(db_session):
    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    candidate = result.candidates[0]
    assert len(result.candidates) <= 10
    assert candidate.extreme_selected
    assert all(c.sample_size == 1 for c in result.claims)
    state = {
        "release": tools.release.version,
        "delivered_fact_ids": [candidate.fact_id],
        "last_subjects": [candidate.subject_id],
        "scope": {},
    }
    next_tools = AnalystTools(
        db_session,
        tools.release,
        "Another one, but about a different player",
        tools.release.season,
        state,
    )
    await next_tools.prepare()
    second = await next_tools.execute(ToolCall(name="discover_facts", question=next_tools.question))
    assert second.candidates
    assert all(c.subject_id != candidate.subject_id for c in second.candidates)
    assert all(c.fact_id != candidate.fact_id for c in second.candidates)
    playoffs = AnalystTools(
        db_session, tools.release, "Now only playoff games", tools.release.season, state
    )
    await playoffs.prepare()
    result = await playoffs.execute(ToolCall(name="discover_facts", question="all games"))
    assert result.status == "no_matching_results" and not result.claims


@pytest.mark.parametrize(
    "change", ["hidden_intro", "missing_coverage", "unknown_reference", "bad_verdict"]
)
async def test_full_answer_review_fails_closed(db_session, change):
    tools, _ = await make_tools(db_session, "Brunson points")
    result = await tools.execute(ToolCall(name="get_player_stats", question=tools.question))
    claim = result.claims[0]
    answer = ProposedAnswer(
        text=claim.statement,
        claims=[ClaimUse(claim_id=claim.claim_id, displayed_value=claim.value)],
    )
    assertion = AssertionReview(
        text=answer.text,
        verdict="supported",
        assertion_type="factual",
        offending_text=None,
        supporting_claim_ids=[claim.claim_id],
        supporting_evidence_ids=[],
        reason="Exact backend calculation.",
    )
    review = AnswerReview(assertions=[assertion])
    assert validate_review(review, answer, tools.claims, tools.evidence)
    if change == "hidden_intro":
        answer = answer.model_copy(update={"text": "His new tactics worked. " + answer.text})
    elif change == "missing_coverage":
        review = AnswerReview(assertions=[assertion.model_copy(update={"text": answer.text[:-1]})])
    elif change == "unknown_reference":
        review = AnswerReview(
            assertions=[assertion.model_copy(update={"supporting_claim_ids": ["x"]})]
        )
    else:
        review = AnswerReview(assertions=[assertion.model_copy(update={"verdict": "unknown"})])
    assert not validate_review(review, answer, tools.claims, tools.evidence)


class ScriptedAdapter:
    """Protocol fixture, deliberately not an evaluation of model quality."""

    def __init__(self):
        self.max_tokens = 0
        self.last_metadata = {"usage": {"cost": 0}, "provider": "protocol-fixture"}
        self.prompts = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        self.prompts.append(payload)
        if payload["schema"]["title"] == "AnswerReview":
            answer = payload["proposed_answer"]
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": answer["text"],
                            "verdict": "supported",
                            "assertion_type": "factual",
                            "offending_text": None,
                            "supporting_claim_ids": [c["claim_id"] for c in answer["claims"]],
                            "supporting_evidence_ids": [],
                            "reason": "Matches backend claims.",
                        }
                    ]
                }
            )
        if not payload["claims"]:
            return json.dumps(
                {
                    "action": "call_tools",
                    "tools": [{"name": "discover_facts", "question": payload["question"]}],
                    "answer": None,
                }
            )
        candidate = next(iter(payload["candidates"]), None)
        claims = (
            [c for c in payload["claims"] if c["claim_id"] in candidate["claim_ids"]]
            if candidate
            else payload["claims"][:1]
        )
        return json.dumps(
            {
                "action": "answer_from_available_evidence",
                "tools": [],
                "answer": {
                    "text": " ".join(c["statement"] for c in claims),
                    "claims": [
                        {"claim_id": c["claim_id"], "displayed_value": c["value"]} for c in claims
                    ],
                    "evidence_ids": [],
                    "fact_ids": [candidate["fact_id"]] if candidate else [],
                },
            }
        )


async def test_bounded_loop_and_revalidated_explanation(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    loop = AnalystLoop(tools, [])
    response = await loop.run()
    assert response["llm_validated"], response
    assert loop.calls == 3 and loop.rounds == 1
    assert response["citations"]
    assert response["state"]["delivered_fact_ids"]
    assert "context" not in adapter.prompts[-1]
    followup = AnalystTools(
        db_session,
        tools.release,
        "Why is that interesting?",
        tools.release.season,
        response["state"],
    )
    await followup.prepare()
    loop2 = AnalystLoop(followup, [])
    result = await loop2.run()
    assert result["llm_validated"] and loop2.calls == 2 and loop2.rounds == 0


async def test_bad_provider_output_counts_call_and_falls_back(db_session, local_redis, monkeypatch):
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)

    class BadAdapter:
        async def generate(self, **kwargs):
            return '{"action":"invented"}'

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", BadAdapter)
    loop = AnalystLoop(tools, [])
    result = await loop.run()
    assert not result["llm_validated"] and loop.calls == 1
    assert result["state"]["delivered_fact_ids"] == []


async def test_release_change_drops_old_claims_and_scope_transition(db_session):
    tools, player = await make_tools(db_session, "Brunson points")
    result = await tools.execute(ToolCall(name="get_player_stats", question=tools.question))
    state = {
        "release": "superseded",
        "claims": [c.model_dump() for c in result.claims],
        "evidence": [e.model_dump() for e in result.evidence],
        "scope": {"player_ids": [player.id]},
        "delivered_fact_ids": ["old"],
    }
    current = AnalystTools(
        db_session, tools.release, "Now only playoff games", tools.release.season, state
    )
    await current.prepare()
    assert not current.claims and not current.evidence
    assert current.scope is not None
    assert current.scope.player_ids == [player.id]
    assert current.scope.season_type == "playoffs"
    assert not current.state["delivered_fact_ids"]


async def test_missing_rows_are_incomplete_not_nonappearances(db_session):
    from app.models.box_score import PlayerGameStat
    from sqlalchemy import delete

    tools, player = await make_tools(db_session, "Brunson points")
    absent = next(s for s, p in tools.rows if p.id == player.id and s.minutes == 0)
    await db_session.execute(delete(PlayerGameStat).where(PlayerGameStat.id == absent.id))
    await db_session.flush()
    current = AnalystTools(db_session, tools.release, tools.question, tools.season, {})
    await current.prepare()
    result = await current.execute(ToolCall(name="get_player_stats", question=tools.question))
    assert result.status == "incomplete_coverage"
    assert result.claims[0].sample_size == 2 and result.claims[0].value == 25
    assert "Missing player rows" in " ".join(result.claims[0].coverage_limitations)


async def test_unknown_entity_and_baseline_scope_fail_closed(db_session):
    tools, _ = await make_tools(db_session, "An interesting stat about Nobody McFake")
    result = await tools.execute(ToolCall(name="discover_facts", question="Brunson"))
    assert result.status == "ambiguous_entity" and not result.claims
    current = AnalystTools(db_session, tools.release, "Brunson points", tools.season, {})
    await current.prepare()
    result = await current.execute(
        ToolCall(
            name="compare_windows",
            question="Brunson points",
            baseline_question="2024-25 regular season",
        )
    )
    assert result.status == "unsupported_metric_or_scope" and not result.claims


async def test_whole_records_fit_budget_and_provenance_is_resolvable(db_session):
    tools, _ = await make_tools(db_session)
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    loop = AnalystLoop(tools, [])
    loop.results.append(result)
    from app.services.analyst_loop import encoded, token_upper_bound
    from app.services.evidence_contracts import Action

    payload = loop.payload(Action)
    assert token_upper_bound(encoded(payload)) + 1700 <= get_settings().analyst_input_tokens
    assert payload["candidates"]
    for claim in payload["claims"]:
        assert claim == tools.claims[claim["claim_id"]].model_dump(mode="json")
        assert all(ref in tools.evidence for ref in claim["supporting_evidence_ids"])


async def test_repair_is_rechecked_and_never_investigates(db_session, local_redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_request_timeout_seconds", 1.0)
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    tools, _ = await make_tools(db_session)

    class RepairAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            if payload["schema"]["title"] == "ProposedAnswer":
                self.prompts.append(payload)
                answer = payload["proposed_answer"]
                answer["text"] = answer["text"].replace(" A new tactic caused this.", "")
                return json.dumps(answer)
            raw = await super().generate(system=system, user=user)
            value = json.loads(raw)
            if payload["schema"]["title"] == "Action" and value.get("answer"):
                value["answer"]["text"] += " A new tactic caused this."
            if (
                payload["schema"]["title"] == "AnswerReview"
                and "tactic" in payload["proposed_answer"]["text"]
            ):
                value["assertions"][0].update(
                    verdict="unsupported",
                    offending_text="A new tactic caused this.",
                    reason="No causal source.",
                )
            return json.dumps(value)

    adapter = RepairAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    loop = AnalystLoop(tools, [])
    result = await loop.run()
    assert result["llm_validated"], result
    assert "tactic" not in result["answer"]
    assert loop.calls == 5 and loop.rounds == 1
    assert [p["schema"]["title"] for p in adapter.prompts][-2:] == [
        "ProposedAnswer",
        "AnswerReview",
    ]


async def test_route_commits_replays_and_ignores_client_authority(client, local_redis, monkeypatch):
    from app.core.db import AsyncSessionLocal

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    request = {
        "question": "Give me an interesting stat",
        "turn_id": "integration-turn-0001",
        "expected_revision": 0,
        "conversation_state": {"player_ids": [999]},
    }
    first = await client.post("/analysis/query", json=request)
    assert first.status_code == 200
    response = first.json()
    assert response["state_committed"] and response["revision"] == 1
    assert response["llm_validated"]
    replay = await client.post("/analysis/query", json=request)
    assert replay.json() == response
    assert len(adapter.prompts) == 3
    conflict = await client.post("/analysis/query", json={**request, "question": "Different input"})
    assert conflict.status_code == 409
    second = await client.post(
        "/analysis/query",
        json={
            "question": "Why is that interesting?",
            "turn_id": "integration-turn-0002",
            "session_token": response["session_token"],
            "expected_revision": 1,
        },
    )
    assert second.json()["llm_validated"] and second.json()["revision"] == 2
    assert len(adapter.prompts) == 5


async def test_redis_failure_gives_explicit_stateless_facts(client, monkeypatch):
    from app.core.db import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)

    async def unavailable():
        return None

    monkeypatch.setattr(analyst_sessions, "_redis", unavailable)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    response = (
        await client.post(
            "/analysis/query", json={"question": "Brunson points", "turn_id": "stateless-turn-0001"}
        )
    ).json()
    assert not response["state_committed"] and response["session_token"] is None
    assert not response["llm_validated"] and response["citations"]
    assert any("Stateless" in warning for warning in response["warnings"])


async def test_six_turn_conversation_protocol(client, local_redis, monkeypatch):
    """State/evidence protocol only; actual-provider acceptance is a separate blocked gate."""
    from app.core.db import AsyncSessionLocal
    from app.models.game import Game
    from sqlalchemy import select

    monkeypatch.setattr(get_settings(), "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(get_settings(), "analysis_answer_mode", "llm_primary")
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    async with AsyncSessionLocal() as db:
        release, _ = await _seed_release_stats(db)
        game = (
            await db.execute(
                select(Game)
                .where(Game.release_id == release.id)
                .order_by(Game.game_date.desc())
                .limit(1)
            )
        ).scalar_one()
        game.season_type = "playoffs"
        await db.commit()

    class ConversationAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            raw = await super().generate(system=system, user=user)
            payload, value = json.loads(user), json.loads(raw)
            if payload["schema"]["title"] == "Action" and value.get("answer"):
                question = payload["question"]
                if "prove" in question:
                    value["answer"]["text"] += (
                        " A single observation does not prove overall improvement."
                    )
                if "injured" in question:
                    value["answer"]["text"] += " I don't have live injury updates."
            return json.dumps(value)

    adapter = ConversationAdapter()
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    questions = [
        "Give me an interesting stat.",
        "Why is that interesting?",
        "Another one, but about a different player.",
        "Now only playoff games.",
        "Does that prove he was playing better?",
        "Is he injured today, and how did he perform in the archived playoffs?",
    ]
    response, outputs = {}, []
    for index, question in enumerate(questions):
        request = {
            "question": question,
            "turn_id": f"six-turn-protocol-{index:03}",
            "session_token": response.get("session_token"),
            "expected_revision": response.get("revision", 0),
        }
        http = await client.post("/analysis/query", json=request)
        assert http.status_code == 200, http.text
        response = http.json()
        assert response["llm_validated"], response
        assert response["state_committed"] and response["revision"] == index + 1
        outputs.append(response)
    first = outputs[0]["citations"][0]["metadata"]["claim"]
    different = outputs[2]["citations"][0]["metadata"]["claim"]
    assert first["subject_id"] != different["subject_id"]
    assert outputs[3]["citations"][0]["metadata"]["claim"]["season_type"] == "playoffs"
    assert "does not prove" in outputs[4]["answer"]
    assert "don't have live injury" in outputs[5]["answer"]
    assert outputs[5]["citations"]


async def test_catalog_preserves_baselines_and_qualifier_population(db_session):
    from datetime import date, timedelta

    from app.models.box_score import PlayerGameStat
    from app.models.game import Game

    tools, player = await make_tools(db_session)
    for i in range(14):
        game = Game(
            release_id=tools.release.id,
            nba_game_id=f"catalog-{i}",
            season=tools.season,
            game_date=date(2026, 2, 1) + timedelta(days=i),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110,
            away_score=100,
            status="final",
            season_type="regular",
            source_name="fixture",
            source_game_id=f"catalog-{i}",
        )
        db_session.add(game)
        await db_session.flush()
        db_session.add(
            PlayerGameStat(
                release_id=tools.release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                minutes=30,
                points=40 if i > 3 else 10,
                field_goals_attempted=20,
            )
        )
    await db_session.flush()
    tools = AnalystTools(
        db_session, tools.release, "Interesting stat about Brunson", tools.season, {}
    )
    await tools.prepare()
    result = await tools.execute(ToolCall(name="discover_facts", question=tools.question))
    assert result.status == "ok", result
    # Inspect all backend catalog claims, not just the bounded ten selected candidates.
    deltas = [c for c in tools.claims.values() if c.metric_id == "points:delta"]
    assert deltas
    delta = deltas[0]
    recent, prior = [tools.claims[ref] for ref in delta.baseline_claim_ids]
    assert recent.sample_size == 10 and prior.sample_size == 6
    assert isinstance(recent.value, (int, float)) and isinstance(prior.value, (int, float))
    assert delta.value == pytest.approx(recent.value - prior.value)
    assert recent.game_ids is not None and prior.game_ids is not None
    assert not set(recent.game_ids) & set(prior.game_ids)
    ranks = [c for c in tools.claims.values() if c.metric_id.endswith(":qualifier_rank")]
    assert ranks and all(c.eligibility["minimum_appearances"] == 4 for c in ranks)


def test_release_gates_require_actual_metrics_and_human_labels():
    from app.evaluation.analyst_evaluation import release_gates

    assert not any(release_gates({}).values())
    gates = release_gates(
        {
            "normal_llm_completion": 0.94,
            "unsupported_claims": 0,
            "reviewed_answers": 0,
            "unsupported_challenges_accepted": 0,
            "human_labelled_challenges": 0,
            "warm_ordinary_p95_ms": 15001,
        }
    )
    assert not gates["normal_llm_completion"]
    assert not gates["heldout_reviewer"]
    assert not gates["unsupported_claims"]
    assert not gates["latency"]
