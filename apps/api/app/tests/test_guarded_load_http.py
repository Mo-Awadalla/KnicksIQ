"""Socket HTTP regressions recorded before the counted warm-load implementation.

Synthetic provider transport and fixture-owned Redis only; these observations
cannot certify original 30-second paid load, Docker identity or publication gates.
Failure modes: altered/replayed requests, wrong phase cap, unselected shadow
transmission, concurrent reservation joins, post-transmission uncertainty and
admission denial. Ordinary minute/day quotas stay enabled.
"""

import asyncio
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import ClassVar

import httpx
import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.verification_adapter import MODEL
from app.evaluation.verification_budget import VerificationBudget
from app.models.game import Game
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import SyntheticAdapter
from app.tests.test_player_intelligence import _seed_release_stats
from sqlalchemy import update


@asynccontextmanager
async def fixture_load(client, redis, monkeypatch, tmp_path, scenario="success", selected=1):
    from app.api.analysis import _sample_shadow
    from app.evaluation.guarded_load import LoadHTTP, load_cases, private_server
    from app.evaluation.guarded_release import GuardedSession, MonthlyLedger
    from app.services import analyst_budget, analyst_loop, runtime_store

    settings = get_settings()
    for name, value in {
        "test_mode": False,
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "shadow",
        "analysis_shadow_sample_rate": 0.1,
        "openrouter_monthly_cutoff_usd": 2.0,
        "analyst_call_reservation_usd": 0.01,
        "public_chat_rate_limit_per_minute": 10,
        "public_chat_rate_limit_per_day": 100,
        "rag_qdrant_enabled": False,
        "sentry_dsn": "",
        "ai_chat_model": MODEL,
        "ip_hash_secret": "synthetic-load-" + str(tmp_path),
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(runtime_store, "_redis", analyst_budget._redis)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
        # The unchanged load includes road wins; the shared analytics seed is home-only.
        await db.execute(
            update(Game)
            .where(Game.source_game_id == "analytics-3")
            .values(home_team_id="BOS", away_team_id="NYK", home_score=100, away_score=113)
        )
        await db.commit()
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.0722179")
    ledger = MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179")
    cases = load_cases(distinct_questions=True)
    # Exercise both sampler outcomes without modifying the sampler or its rate.
    identities = []
    for index, _case in enumerate(cases):
        desired = index in range(selected)
        identity = next(
            f"synthetic-load-{index}-{n}"
            for n in range(10000)
            if _sample_shadow(f"synthetic-load-{index}-{n}", 0.1) == desired
        )
        identities.append(identity)
    journal = tmp_path / "goal.sqlite"
    VerificationBudget.create(journal, binding="synthetic-load", shadow_selected=1)
    budget = VerificationBudget(journal, binding="synthetic-load")
    with budget._connect() as db:
        db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
        db.execute(
            "INSERT INTO guard_goal VALUES (?)",
            (json.dumps({"historical_floor_nusd": 72_217_900}),),
        )
        if scenario == "cap":
            db.execute("UPDATE stages SET request_cap=0 WHERE name='load'")
    seen = []

    class RequestedTeamProtocol(SyntheticAdapter):
        async def generate(self, *, system, user):
            prompt = json.loads(user)
            if not prompt["claims"] and prompt["schema"]["title"] != "AnswerReview":
                return json.dumps(
                    {
                        "action": "call_tools",
                        "tools": [{"name": "get_team_stats", "question": prompt["question"]}],
                        "answer": None,
                    }
                )
            return await super().generate(system=system, user=user)

    protocol = RequestedTeamProtocol({"name": "get_team_stats", "question": cases[0]["question"]})

    class SyntheticAdmission:
        cases: ClassVar[list[dict]]
        contract_sha256 = "synthetic-load"

        async def verify_environment(self, identity):
            await session.ledger.read()

        async def verify_request(self, payload, owned):
            await session.ledger.read(owned)
            if scenario == "deny":
                raise ValueError("Synthetic live admission denied")
            return {
                "bound_nusd": 1_000_000,
                "route": "morph/fp8",
                "provider": "Morph",
                "metadata_sha256": "synthetic",
            }

    SyntheticAdmission.cases = cases

    async def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        generation = f"fixture-load-{len(seen)}"
        await asyncio.sleep(0.02)
        if scenario == "uncertain":
            raise httpx.ReadTimeout("fixture interruption after transmission", request=request)
        raw = await protocol.generate(
            system=payload["messages"][0]["content"], user=payload["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": generation,
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": 0.000001},
                "choices": [{"message": {"content": raw}}],
            },
        )

    session = GuardedSession(
        admission=SyntheticAdmission(),
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode="shadow",
        stage="load",
        cases=cases,
        request_ids=identities,
        run_dir=tmp_path / "run",
        provider_transport=httpx.MockTransport(respond),
    )
    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter("load", None)
        )
        from app.main import create_app

        wrapper = LoadHTTP(create_app(), session, cases, identities)
        async with private_server(wrapper, lifespan="off") as base_url:
            async with httpx.AsyncClient(base_url=base_url, timeout=60) as http:
                yield http, wrapper, session, budget, seen, key


async def test_original_load_socket_binds_exact_raw_question_once(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,  # noqa: F811
):  # noqa: F811
    async with fixture_load(client, local_redis, monkeypatch, tmp_path) as (
        http,
        wrapper,
        session,
        budget,
        seen,
        key,
    ):
        assert (await http.get("/health/ready")).status_code == 200
        case = wrapper.cases[0]
        response = await http.post(
            "/analysis/query", json={"question": case["question"], "season": "2025-26"}
        )
        assert response.status_code == 200 and response.json()["citations"]
        assert response.json()["request_id"] == wrapper.request_ids[0]
        assert seen and all(
            row["mode"] == "shadow" and row["stage"] == "load" for row in session.receipts()
        )
        assert budget.snapshot()["stages"]["load"]["requests"] == len(seen)
        assert await local_redis.hlen(key + ":reservations") == 0
        replay = await http.post(
            "/analysis/query", json={"question": case["question"], "season": "2025-26"}
        )
        assert replay.status_code == 409 and budget.snapshot()["stopped"]


@pytest.mark.parametrize("corruption", [None, "stage", "mode", "cost", "binding"])
async def test_load_socket_aggregate_receipts_join_counted_stage_not_answer_mode(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    corruption,
):
    async with fixture_load(client, local_redis, monkeypatch, tmp_path) as (
        http,
        wrapper,
        session,
        budget,
        seen,
        key,
    ):
        response = await http.post(
            "/analysis/query",
            json={"question": wrapper.cases[0]["question"], "season": "2025-26"},
        )
        assert response.status_code == 200 and seen
        rows = session.receipts()
        assert all(row["stage"] == "load" and row["mode"] == "shadow" for row in rows)
        if corruption is not None:
            row = dict(rows[0])
            row[
                {
                    "stage": "stage",
                    "mode": "mode",
                    "cost": "cost_nusd",
                    "binding": "journal_binding",
                }[corruption]
            ] = {
                "stage": "shadow",
                "mode": "primary",
                "cost": row["cost_nusd"] + 1,
                "binding": "foreign-goal",
            }[corruption]
            with budget._connect() as db:
                db.execute(
                    "UPDATE guard_receipts SET receipt=? WHERE ticket=?",
                    (json.dumps(row), row["journal_ticket"]),
                )
            with pytest.raises(ValueError, match="counted case/provider cost join"):
                session.validate_receipt_joins()
        else:
            session.validate_receipt_joins()
        assert await local_redis.hlen(key + ":reservations") == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "Changed original question", "season": "2025-26"},
        {"question": "What was the Knicks record this season?", "season": "2024-25"},
        {
            "question": "What was the Knicks record this season?",
            "season": "2025-26",
            "turn_id": "forged",
        },
    ],
)
async def test_load_changed_raw_binding_denied_before_provider(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    payload,  # noqa: F811
):  # noqa: F811
    async with fixture_load(client, local_redis, monkeypatch, tmp_path) as (
        http,
        wrapper,
        session,
        budget,
        seen,
        key,
    ):
        response = await http.post("/analysis/query", json=payload)
        assert response.status_code == 409
        assert not seen and not session.receipts() and budget.snapshot()["stopped"]


@pytest.mark.parametrize("scenario", ["cap", "deny", "uncertain"])
async def test_load_socket_failure_retains_exact_counted_exposure(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    scenario,  # noqa: F811
):  # noqa: F811
    async with fixture_load(client, local_redis, monkeypatch, tmp_path, scenario) as (
        http,
        wrapper,
        session,
        budget,
        seen,
        key,
    ):
        case = wrapper.cases[0]
        await http.post("/analysis/query", json={"question": case["question"], "season": "2025-26"})
        assert budget.snapshot()["stopped"] and session.execution.failure
        if scenario == "uncertain":
            assert len(seen) == 1 and session.receipts()[0]["status"] == "uncertain"
            assert session.receipts()[0]["request_id"] == wrapper.request_ids[0]
            assert await local_redis.hlen(key + ":reservations") == 1
            assert await local_redis.ttl(key) == -1
        else:
            assert not seen and not session.receipts()
        later = await http.post(
            "/analysis/query", json={"question": wrapper.cases[1]["question"], "season": "2025-26"}
        )
        assert later.status_code == 503
        assert len(seen) == (1 if scenario == "uncertain" else 0)


async def test_selected_concurrent_load_and_unselected_shadow_keep_independent_joins(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,  # noqa: F811
):  # noqa: F811
    async with fixture_load(client, local_redis, monkeypatch, tmp_path, selected=3) as (
        http,
        wrapper,
        session,
        budget,
        seen,
        key,
    ):
        responses = await asyncio.gather(
            *[
                http.post(
                    "/analysis/query", json={"question": case["question"], "season": "2025-26"}
                )
                for case in wrapper.cases[:4]
            ]
        )
        assert all(response.status_code == 200 for response in responses)
        assert not budget.snapshot()["stopped"]
        rows = session.receipts()
        assert rows and {row["request_id"] for row in rows} == set(wrapper.request_ids[:3])
        assert wrapper.request_ids[3] not in {row["request_id"] for row in rows}
        assert len({row["journal_ticket"] for row in rows}) == len(rows) == len(seen)
        assert all(row["status"] == "settled" and row["stage"] == "load" for row in rows)
        assert await local_redis.hlen(key + ":reservations") == 0


def test_original_load_cli_changed_frozen_input_never_opens_socket_or_resets_goal(tmp_path):
    contract = tmp_path / "source-support-20261003/gold-review/frozen-expectations.json"
    contract.parent.mkdir(parents=True)
    contract.write_text('{"cases": []}')
    goal = tmp_path / "already-admitted"
    goal.mkdir()
    journal = goal / "goal.sqlite"
    VerificationBudget.create(journal, binding="retained-goal", shadow_selected=1)
    before = journal.read_bytes()
    bootstrap = (
        "import socket,ssl,runpy,sys,httpx; "
        "socket.socket=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.argv=sys.argv[1:]; runpy.run_module('app.evaluation.guarded_load',run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            bootstrap,
            "load",
            "--evidence-root",
            str(tmp_path),
            "--goal-dir",
            str(goal),
            "--disabled-score",
            str(tmp_path / "score.json"),
            "--disabled-observations",
            str(tmp_path / "observations.json"),
            "--primary-score",
            str(tmp_path / "primary-score.json"),
            "--shadow-score",
            str(tmp_path / "shadow-score.json"),
            "--shadow-record",
            str(tmp_path / "shadow-record.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["status"] == "denied_or_stopped"
    assert "network forbidden" not in result.stderr
    assert journal.read_bytes() == before
    assert not (goal / "load").exists()


@pytest.mark.parametrize("phases", [[], ["primary"], ["shadow"], ["primary", "shadow"]])
async def test_original_load_denies_unreviewed_quality_before_socket_or_reservation(
    monkeypatch, tmp_path, phases
):
    """Completed transport/fallback runs are not successful original quality gates."""
    import hashlib
    from types import SimpleNamespace

    from app.evaluation import guarded_load as load
    from app.evaluation.guarded_release import GOAL_ANCHOR, MonthlyLedger, digest
    from app.evaluation.verification_budget import SPENDING_DIRECTION_SHA256

    root, goal = tmp_path, tmp_path / "goal"
    goal.mkdir()
    key = "synthetic-only-never-transmitted"
    monkeypatch.setattr(get_settings(), "openrouter_api_key", key)
    monkeypatch.setattr(load, "DESIGNATED_KEY_SHA256", hashlib.sha256(key.encode()).hexdigest())
    monkeypatch.setattr(load, "FROZEN", {load.GOLD: "synthetic-gold"})
    real_file_hash = load.file_hash
    monkeypatch.setattr(
        load,
        "file_hash",
        lambda path: "synthetic-gold" if path == root / load.GOLD else real_file_hash(path),
    )
    from app.api.analysis import _sample_shadow
    from app.services.release_evidence import evaluation_request_id
    from app.tests.test_release_evaluation import fixture_contract

    identity = {
        "cases": load.load_cases(distinct_questions=True),
        "request_ids": [f"fixture-denied-load-{index}" for index in range(11)],
        "shadow_membership": [True] + [False] * 10,
    }
    monkeypatch.setattr(load, "load_identity", lambda: identity)
    monkeypatch.setattr(load, "disabled_pass", lambda *args: {"status": "synthetic-disabled"})
    contract = fixture_contract()
    monkeypatch.setattr(load, "load_contract", lambda *args: contract)
    selected = sum(
        _sample_shadow(evaluation_request_id("synthetic-gold", "shadow", case["id"]), 0.1)
        for case in contract["cases"]
    )
    binding = {
        "historical_floor_nusd": 72_217_900,
        "redis_run_id": "synthetic",
        "resources": {"qdrant_aliases": {}},
    }
    monkeypatch.setattr(
        load,
        "goal_context",
        lambda *args: (
            MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179"),
            binding,
            root / GOAL_ANCHOR,
        ),
    )
    binding_sha = digest(binding)
    (root / GOAL_ANCHOR).parent.mkdir(parents=True)
    (root / GOAL_ANCHOR).write_text(
        json.dumps({"goal_dir": str(goal), "binding_sha256": binding_sha})
    )
    VerificationBudget.create(goal / "goal.sqlite", binding=binding_sha, shadow_selected=selected)
    budget = VerificationBudget(goal / "goal.sqlite", binding=binding_sha)
    with budget._connect() as db:
        db.execute("CREATE TABLE spending_direction (sha256 TEXT NOT NULL)")
        db.execute("INSERT INTO spending_direction VALUES (?)", (SPENDING_DIRECTION_SHA256,))
        db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
        db.execute("INSERT INTO guard_goal VALUES (?)", (json.dumps(binding),))
        db.execute("CREATE TABLE guard_runs (mode TEXT PRIMARY KEY, status TEXT NOT NULL)")
        db.executemany(
            "INSERT INTO guard_runs VALUES (?, 'complete')", [(phase,) for phase in phases]
        )
    opened = []

    class SyntheticAdmission:
        contract_sha256 = "synthetic-gold"
        cases = identity["cases"]

        def __init__(self, **kwargs):
            pass

        async def verify_environment(self, observed):
            assert observed == identity

    monkeypatch.setattr(load, "LoadAdmission", SyntheticAdmission)

    def forbidden_socket(*args, **kwargs):
        opened.append(True)
        raise AssertionError("Quality denial must precede socket/provider admission")

    monkeypatch.setattr(load, "private_server", forbidden_socket)
    args = SimpleNamespace(
        evidence_root=root,
        goal_dir=goal,
        disabled_score=root / "disabled-score.json",
        disabled_observations=root / "disabled-observations.json",
        primary_score=root / "missing-primary-score.json",
        shadow_score=root / "missing-shadow-score.json",
        shadow_record=root / "missing-shadow-record.json",
        port=0,
    )
    with pytest.raises(ValueError, match="original primary.*shadow quality"):
        await load.run(args)
    assert not opened and budget.snapshot()["calls"] == []
    with budget._connect() as db:
        assert db.execute("SELECT 1 FROM guard_runs WHERE mode='load'").fetchone() is None
    assert not (goal / "load").exists()
