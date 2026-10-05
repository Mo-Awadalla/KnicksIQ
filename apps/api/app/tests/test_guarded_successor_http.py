"""Disposable consumer regressions specified before successor implementation.

Failure modes: implicit new goal, missing/changed/replayed approval, substituted
predecessor, active or SHA-changed predecessor, mismatched lineage/phase caps,
missing/lowered/foreign retained holds, lowered monthly floor, inherited requests
lost at a stage ceiling, old first-turn response replayed under fixed request IDs,
and typed malformed content continuing or losing its settled cost/raw diagnosis.
Only disposable journals, isolated Redis and fake provider responses are used.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation import guarded_release as guard
from app.evaluation.guarded_load import private_server
from app.evaluation.release_runner import digest, file_hash
from app.evaluation.verification_adapter import MODEL
from app.evaluation.verification_budget import SPENDING_DIRECTION_SHA256, VerificationBudget
from app.services.release_evidence import evaluation_request_id
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from app.tests.test_release_evaluation import fixture_contract

HELD = {"old-held-a": "0.03", "old-held-b": "0.02"}


@pytest.fixture
async def successor_fixture(client, local_redis, monkeypatch, tmp_path):  # noqa: F811
    settings = get_settings()
    for name, value in {
        "test_mode": False,
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary",
        "analysis_shadow_sample_rate": 0.1,
        "openrouter_monthly_cutoff_usd": 2.0,
        "analyst_call_reservation_usd": 0.01,
        "rag_qdrant_enabled": False,
        "sentry_dsn": "",
        "ai_chat_model": MODEL,
        "ai_provider": "none",
        "openrouter_api_key": "sk-or-disposable-never-live",
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert settings.openrouter_api_key is not None
    monkeypatch.setattr(
        guard,
        "DESIGNATED_KEY_SHA256",
        hashlib.sha256(settings.openrouter_api_key.encode()).hexdigest(),
    )
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    root = tmp_path
    for relative, content in {
        guard.GOLD: fixture_contract(),
        guard.HISTORY: {
            "provider_calls": 22,
            "ledger_floor_usd": "0.0722179",
            "retained_unknown_usd": "0.07205728",
        },
        guard.PRIOR_PROBE: {"disposable": True},
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content))
    approval = root / guard.APPROVAL
    approval.write_text(
        json.dumps(
            {
                "owner": "synthetic",
                "approved_at": "2026-01-01",
                "expectations_sha256": file_hash(root / guard.GOLD),
            }
        )
    )
    frozen = {
        relative: file_hash(root / relative)
        for relative in (guard.GOLD, guard.APPROVAL, guard.HISTORY, guard.PRIOR_PROBE)
    }
    monkeypatch.setattr(guard, "FROZEN", frozen)
    from app.api.analysis import _sample_shadow

    cases = fixture_contract()["cases"]
    selected = sum(
        _sample_shadow(evaluation_request_id(frozen[guard.GOLD], "shadow", c["id"]), 0.1)
        for c in cases
    )
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.372507682")
    await local_redis.hset(key + ":reservations", mapping=HELD)
    server_id = (await local_redis.info("server"))["run_id"]
    ledger = guard.MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179")
    old_binding = guard.goal_binding(root, ledger)
    old_sha = digest(old_binding)
    old_binding.update(
        historical_floor_nusd=319_106_710, redis_run_id=server_id, resources={"qdrant_aliases": {}}
    )
    predecessor = root / "predecessor"
    predecessor.mkdir()
    VerificationBudget.create(
        predecessor / "goal.sqlite", binding=old_sha, shadow_selected=selected
    )
    old = VerificationBudget(predecessor / "goal.sqlite", binding=old_sha)
    with old._connect() as db:
        db.execute("CREATE TABLE spending_direction (sha256 TEXT NOT NULL)")
        db.execute("INSERT INTO spending_direction VALUES (?)", (SPENDING_DIRECTION_SHA256,))
        db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
        db.execute("INSERT INTO guard_goal VALUES (?)", (json.dumps(old_binding),))
        db.execute("CREATE TABLE guard_runs (mode TEXT PRIMARY KEY, status TEXT NOT NULL)")
        db.execute("INSERT INTO guard_runs VALUES ('primary', 'failed')")
        db.execute(
            "CREATE TABLE guard_receipts (ticket INTEGER PRIMARY KEY, receipt TEXT NOT NULL, "
            "generation TEXT UNIQUE)"
        )
        db.execute("CREATE TABLE guard_normal (identity TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
        for index in range(1, 27):
            uncertain = index == 26
            cost = 1_152_354 if uncertain else 1000
            db.execute(
                "INSERT INTO calls VALUES (?, 'primary', ?, ?, ?)",
                (
                    index,
                    cost,
                    "failed" if uncertain else "settled",
                    "CancelledError" if uncertain else None,
                ),
            )
            receipt = {
                "journal_ticket": index,
                "journal_binding": old_sha,
                "stage": "primary",
                "mode": "primary",
                "normal_reservation_id": "old-held-b" if uncertain else "old-held-a",
                "request_id": evaluation_request_id(frozen[guard.GOLD], "primary", cases[0]["id"]),
                "case_id": cases[0]["id"],
                "bound_nusd": 1_152_354,
                "status": "uncertain" if uncertain else "settled",
            }
            if not uncertain:
                receipt["cost_nusd"] = cost
            db.execute(
                "INSERT INTO guard_receipts VALUES (?, ?, ?)",
                (index, json.dumps(receipt), f"old-{index}"),
            )
        for identity, amount in HELD.items():
            normal = {
                "identity": identity,
                "amount": amount,
                "settled": False,
                "uncertain": True,
                "tickets": list(range(1, 26)) if identity == "old-held-a" else [26],
            }
            db.execute("INSERT INTO guard_normal VALUES (?, ?)", (identity, json.dumps(normal)))
        db.execute("UPDATE identity SET stopped=1")
    (predecessor / "goal-binding.json").write_text(
        json.dumps({"binding_sha256": old_sha, **old_binding})
    )
    anchor = root / guard.GOAL_ANCHOR
    anchor.write_text(json.dumps({"goal_dir": str(predecessor), "binding_sha256": old_sha}))
    authorization = root / "authorization.private.json"
    authorization.write_text(
        json.dumps(
            {
                "scope": (
                    "Separate counted live attempt, not reset/resume of stopped attempt; "
                    "full original frozen workloads, no launch or alias promotion"
                ),
                "authorized_at": "2026-10-05T00:51:27.566981+00:00",
                "user_funding_statement": "disposable owner funding statement",
                "user_safety_choice": "New counted live attempt",
                "predecessor_goal": "/evidence/predecessor",
                "predecessor_journal_sha256": file_hash(predecessor / "goal.sqlite"),
                "preserve_all_predecessor_charges_and_reservations": True,
                "funding_added_usd": "5",
                "original_case_and_request_limits_remain": True,
                "monthly_cutoff_usd_remains": "2",
                "expected_frozen_contract_sha256": frozen[guard.GOLD],
            }
        )
    )
    monkeypatch.setattr(
        guard, "SUCCESSOR_AUTHORIZATION_SHA256", file_hash(authorization), raising=False
    )
    admissions = []

    class ResourceAdmission:
        contract_sha256 = frozen[guard.GOLD]

        def __init__(self, *, ledger, **kwargs):
            self.ledger = ledger
            self.resource_binding = {"qdrant_aliases": {}}
            self.alias_binding = {}
            self.cases = cases
            admissions.append(self)

        def verify_inputs(self):
            assert file_hash(root / guard.GOLD) == frozen[guard.GOLD]

        async def verify_environment(self, identity):
            assert len(identity["request_ids"]) == 120
            self.ledger.run_id = server_id
            await self.ledger.read()

        async def verify_request(self, payload, owned):
            await self.ledger.read(owned)
            return {
                "bound_nusd": 1_000_000,
                "provider": "Morph",
                "route": "morph/fp8",
                "metadata_sha256": "synthetic",
            }

    monkeypatch.setattr(guard, "Admission", ResourceAdmission)
    args = SimpleNamespace(
        action="admit",
        mode="primary",
        evidence_root=root,
        goal_dir=root / "successor",
        successor_authorization=authorization,
        predecessor_goal=predecessor,
        spending_direction=None,
    )

    # Only the spending-direction file boundary is synthetic; the controller and
    # actual journal creation/lineage validation remain real executable code.
    def apply_direction(self, path):
        with self._connect() as db:
            db.execute("CREATE TABLE spending_direction (sha256 TEXT NOT NULL)")
            db.execute("INSERT INTO spending_direction VALUES (?)", (SPENDING_DIRECTION_SHA256,))

    monkeypatch.setattr(VerificationBudget, "apply_spending_direction", apply_direction)
    args.spending_direction = root / "synthetic-direction.json"
    yield SimpleNamespace(
        args=args,
        root=root,
        predecessor=predecessor,
        old=old,
        authorization=authorization,
        redis=local_redis,
        key=key,
        selected=selected,
        cases=cases,
        admissions=admissions,
        original_bytes=(predecessor / "goal.sqlite").read_bytes(),
        anchor_bytes=anchor.read_bytes(),
    )


def refresh_disposable_authorization(fixture, monkeypatch):
    auth = json.loads(fixture.authorization.read_text())
    auth["predecessor_journal_sha256"] = file_hash(fixture.predecessor / "goal.sqlite")
    fixture.authorization.write_text(json.dumps(auth))
    monkeypatch.setattr(guard, "SUCCESSOR_AUTHORIZATION_SHA256", file_hash(fixture.authorization))


@pytest.mark.parametrize(
    "fault",
    [
        "unauthorized",
        "half_flags",
        "substituted",
        "wrong_predecessor",
        "active",
        "journal_sha",
        "binding",
        "cap",
        "missing_hold",
        "lower_hold",
        "foreign_hold",
        "floor",
        "authoritative_floor",
    ],
)
async def test_successor_admission_denies_unsafe_lineage_before_transport(
    successor_fixture, monkeypatch, fault
):
    f = successor_fixture
    if fault == "unauthorized":
        f.args.successor_authorization = f.args.predecessor_goal = None
    elif fault == "half_flags":
        f.args.predecessor_goal = None
    elif fault == "wrong_predecessor":
        f.args.predecessor_goal = f.root / "foreign-predecessor"
    elif fault == "substituted":
        f.authorization.write_text(f.authorization.read_text() + " ")
    elif fault in {"active", "journal_sha", "binding", "cap"}:
        with f.old._connect() as db:
            if fault == "active":
                db.execute("UPDATE identity SET stopped=0")
            elif fault == "binding":
                db.execute("UPDATE identity SET binding='substituted'")
            elif fault == "cap":
                db.execute("UPDATE stages SET request_cap=721 WHERE name='primary'")
            else:
                db.execute("UPDATE calls SET error='changed' WHERE id=26")
        if fault != "journal_sha":
            refresh_disposable_authorization(f, monkeypatch)
    elif fault == "missing_hold":
        await f.redis.hdel(f.key + ":reservations", "old-held-a")
    elif fault == "lower_hold":
        await f.redis.hset(f.key + ":reservations", "old-held-a", "0.02")
    elif fault == "foreign_hold":
        await f.redis.hset(f.key + ":reservations", "foreign", "0.01")
    elif fault == "floor":
        await f.redis.set(f.key, "0.1")
    elif fault == "authoritative_floor":
        await f.redis.set(f.key, "0.35")
    before = (f.predecessor / "goal.sqlite").read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (f.predecessor / "goal.sqlite").read_bytes() == before
    assert (f.root / guard.GOAL_ANCHOR).read_bytes() == f.anchor_bytes


async def test_successor_authorization_is_exclusive_and_retains_all_original_accounting(
    successor_fixture, record_property
):
    f = successor_fixture
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    snapshot = budget.snapshot()
    assert snapshot["stages"]["primary"]["requests"] == 26
    assert snapshot["reserved_or_spent_nusd"] == 1_177_354
    assert snapshot["inherited_calls"] == f.old.snapshot()["calls"]
    assert budget.request_cap("primary") == 720
    assert budget.request_cap("shadow") == 6 * f.selected
    assert budget.request_cap("load") == 66 and budget.request_cap("smoke") == 9
    assert binding["historical_floor_nusd"] == 372_507_682
    assert binding["successor"]["authorization_sha256"] == file_hash(f.authorization)
    assert binding["successor"]["retained_reservations"] == HELD
    assert binding["guarded_cli_sha256"] == file_hash(Path(guard.__file__))
    f.args.goal_dir = f.root / "duplicate-successor"
    with pytest.raises((ValueError, FileExistsError)):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    assert (f.root / guard.GOAL_ANCHOR).read_bytes() == f.anchor_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == {
        k.encode(): v.encode() for k, v in HELD.items()
    }
    record_property("counted_successor_binding", str(binding))


async def test_successor_actual_collection_stops_first_typed_invalid_and_keeps_private_raw_cost(
    successor_fixture, monkeypatch, record_property
):
    f = successor_fixture
    await guard.run(f.args)
    bodies = []
    original_session = guard.GuardedSession

    async def respond(request):
        raw = json.dumps(
            {
                "id": "new-malformed-generation",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": 0.000001},
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            }
        ).encode()
        bodies.append(raw)
        return httpx.Response(200, content=raw)

    def session(**kwargs):
        return original_session(**kwargs, provider_transport=httpx.MockTransport(respond))

    monkeypatch.setattr(guard, "GuardedSession", session)
    f.args.action = "collect"
    with pytest.raises(ValueError):
        await guard.run(f.args)
    summary = json.loads((f.args.goal_dir / "primary/execution-summary.json").read_text())
    assert len(bodies) == 1
    assert summary["accounting"]["stopped"]
    assert summary["accounting"]["stages"]["primary"]["requests"] == 27
    assert summary["accounting"]["calls"][0]["status"] == "settled"
    assert summary["accounting"]["calls"][0]["amount_nusd"] == 1000
    ticket = summary["calls"][0]["journal_ticket"]
    raw_path = f.args.goal_dir / "primary" / f"response-{ticket:06d}.body"
    assert raw_path.read_bytes() == bodies[0]
    assert raw_path.stat().st_mode & 0o777 == 0o600
    reservations = await f.redis.hgetall(f.key + ":reservations")
    assert len(reservations) == 2
    assert all(reservations[k.encode()] == v.encode() for k, v in HELD.items())
    diagnosis = json.loads(
        (f.args.goal_dir / "primary" / f"protocol-failure-{ticket:06d}.json").read_text()
    )
    assert diagnosis["error_type"] == "ValidationError"
    assert diagnosis["finish_reason"] == "stop"
    assert any(
        item["loc"] == ["action"] and item["type"] == "missing" for item in diagnosis["errors"]
    )
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    record_property(
        "successor_protocol_stop", str(f.args.goal_dir / "primary/execution-summary.json")
    )


async def test_successor_socket_does_not_replay_old_fixed_turn_and_preserves_shadow_identity(
    successor_fixture, monkeypatch, record_property
):
    from app import main
    from app.evaluation.trace_capture import capture_turn
    from app.services import analyst_loop
    from app.tests.test_analyst_contracts import ScriptedAdapter

    f = successor_fixture
    # Seed a real predecessor first-turn response under the unchanged collector
    # client and exact request ID; do not delete/reset any chat/quota state.
    case = next(c for c in f.cases if "brunson" in c["question"].lower())
    index = f.cases.index(case)
    request_id = evaluation_request_id(file_hash(f.root / guard.GOLD), "primary", case["id"])
    payload = {
        "question": case["question"],
        "season": "2025-26",
        "context": case.get("context", []),
        "turn_id": request_id,
        "expected_revision": 0,
    }
    # Deterministic is the ordinary model-disabled mode. Seed only chat state:
    # no fake zero-cost reserve/refund can round down the authoritative floor.
    with monkeypatch.context() as seed:
        seed.setattr(get_settings(), "analysis_answer_mode", "deterministic")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                main.create_app(), client=(f"192.0.2.{index + 1}", 12345)
            ),
            base_url="https://test",
        ) as old_http:
            with capture_turn() as old_capture:
                old_response = await old_http.post(
                    "/analysis/query", json=payload, headers={"x-request-id": request_id}
                )
    assert old_response.status_code == 200
    assert old_response.json()["state_committed"] is True
    assert old_capture["turn"]["replayed"] is False
    assert old_capture["turn"]["model_calls"] == 0
    assert await f.redis.get(f.key) == b"0.372507682"
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    ledger = guard.MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}",
        historical_floor=str(binding["historical_floor_nusd"] / 1e9),
        retained=HELD,
    )
    protocol, seen = ScriptedAdapter(), []

    async def respond(request):
        data = json.loads(request.content)
        seen.append(data)
        content = await protocol.generate(
            system=data["messages"][0]["content"], user=data["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": f"socket-generation-{len(seen)}",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": 0.000001},
                "choices": [{"message": {"content": content}}],
            },
        )

    session = guard.GuardedSession(
        admission=f.admissions[-1],
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode="primary",
        run_dir=f.args.goal_dir / "socket",
        provider_transport=httpx.MockTransport(respond),
    )
    captures = []
    app = None

    async def captured_app(scope, receive, send):
        with capture_turn() as capture:
            assert app is not None
            await app(scope, receive, send)
            if scope["type"] == "http" and scope["path"] == "/analysis/query":
                captures.append(capture)

    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter("primary", None)
        )
        app = main.create_app()
        async with private_server(captured_app, lifespan="off") as url:
            async with httpx.AsyncClient(base_url=url) as http:
                fresh = await http.post(
                    "/analysis/query", json=payload, headers={"x-request-id": request_id}
                )
                replay = await http.post(
                    "/analysis/query", json=payload, headers={"x-request-id": request_id}
                )
    evidence = session.run_dir / "socket-evidence.json"
    guard.durable_json(
        evidence,
        {
            "old_response": old_response.json(),
            "old_capture": old_capture,
            "fresh_response": fresh.json(),
            "replay_response": replay.json(),
            "captures": captures,
            "transmissions": len(seen),
            "receipts": session.receipts(),
            "accounting": budget.snapshot(),
            "subject_namespace": session.subject_namespace,
        },
    )
    record_property("successor_socket_evidence", str(evidence))
    assert fresh.status_code == 200 and fresh.json()["llm_validated"]
    assert captures[0]["turn"]["replayed"] is False
    assert fresh.json()["request_id"] == request_id
    assert replay.json() == fresh.json()
    assert seen and all(row["request_id"] == request_id for row in session.receipts())
    assert await f.redis.hgetall(f.key + ":reservations") == {
        k.encode(): v.encode() for k, v in HELD.items()
    }
    from app.api.analysis import _sample_shadow

    shadow_ids = [
        evaluation_request_id(file_hash(f.root / guard.GOLD), "shadow", c["id"]) for c in f.cases
    ]
    assert sum(_sample_shadow(identity, 0.1) for identity in shadow_ids) == f.selected
    record_property("successor_socket_calls", str(session.run_dir))


def fill_original_stage(f, monkeypatch, stage, cap):
    with f.old._connect() as db:
        db.execute("DELETE FROM calls")
        db.execute("DELETE FROM guard_receipts")
        for ticket in range(1, cap + 1):
            db.execute("INSERT INTO calls VALUES (?, ?, 0, 'settled', NULL)", (ticket, stage))
            row = {
                "journal_ticket": ticket,
                "journal_binding": db.execute("SELECT binding FROM identity").fetchone()[0],
                "stage": stage,
                "mode": "shadow" if stage == "load" else stage,
                "status": "settled",
                "cost_nusd": 0,
                "normal_reservation_id": "old-held-a",
                "request_id": "synthetic",
                "bound_nusd": 1_000_000,
            }
            db.execute(
                "INSERT INTO guard_receipts VALUES (?, ?, ?)",
                (ticket, json.dumps(row), f"old-{ticket}"),
            )
        for identity, amount in HELD.items():
            row = {
                "identity": identity,
                "amount": amount,
                "settled": False,
                "uncertain": True,
                "tickets": list(range(1, cap + 1)) if identity == "old-held-a" else [],
            }
            db.execute(
                "UPDATE guard_normal SET receipt=? WHERE identity=?", (json.dumps(row), identity)
            )
    refresh_disposable_authorization(f, monkeypatch)
    f.original_bytes = (f.predecessor / "goal.sqlite").read_bytes()


@pytest.mark.parametrize(
    "stage,cap", [("primary", 720), ("shadow", 48), ("load", 66), ("smoke", 9)]
)
async def test_successor_inherited_requests_exhaust_original_ceiling_before_send(
    successor_fixture, monkeypatch, stage, cap
):
    f = successor_fixture
    if stage == "shadow":
        cap = 6 * f.selected
    fill_original_stage(f, monkeypatch, stage, cap)
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    sent = []

    async def forbidden_send():
        sent.append(True)
        raise AssertionError("Inherited phase requests must deny before provider transmission")

    with pytest.raises(ValueError):
        await budget.call(stage, 1_000_000, forbidden_send)
    assert not sent and budget.snapshot()["stages"][stage]["requests"] == cap
    assert budget.request_cap(stage) == cap


async def stop_with_known_protocol_cost(f, monkeypatch, *, cost=0.00004213, valid_first=False):
    """Exercise the real collector, transport, settlement and private failure artifacts."""
    from app.tests.test_analyst_contracts import ScriptedAdapter

    original_session = guard.GuardedSession
    protocol, bodies = ScriptedAdapter(), []
    answered = False

    async def respond(request):
        nonlocal answered
        data = json.loads(request.content)
        content = "{}"
        if valid_first and not answered:
            content = await protocol.generate(
                system=data["messages"][0]["content"], user=data["messages"][1]["content"]
            )
            answered = (
                json.loads(data["messages"][1]["content"])["schema"]["title"] == "AnswerReview"
            )
        raw = json.dumps(
            {
                "id": f"{f.args.goal_dir.name}-generation-{len(bodies) + 1}",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": cost},
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            }
        ).encode()
        bodies.append(raw)
        return httpx.Response(200, content=raw)

    with monkeypatch.context() as transport:
        transport.setattr(
            guard,
            "GuardedSession",
            lambda **kwargs: original_session(
                **kwargs, provider_transport=httpx.MockTransport(respond)
            ),
        )
        f.args.action = "collect"
        with pytest.raises(ValueError):
            await guard.run(f.args)
    summary = json.loads((f.args.goal_dir / "primary/execution-summary.json").read_text())
    assert summary["status"] == "failed" and bodies
    assert all(row["status"] == "settled" for row in summary["accounting"]["calls"])
    assert all(row["status"] == "settled" for row in summary["calls"])
    ticket = summary["calls"][-1]["journal_ticket"]
    assert (f.args.goal_dir / "primary" / f"protocol-failure-{ticket:06d}.json").is_file()
    assert (f.args.goal_dir / "primary" / f"response-{ticket:06d}.body").read_bytes() == bodies[-1]
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    verified_floor = binding["historical_floor_nusd"] + sum(
        row["amount_nusd"] for row in summary["accounting"]["calls"]
    )
    raw_monthly = (await f.redis.get(f.key)).decode()
    observed_nusd = Decimal(raw_monthly) * 1_000_000_000
    held = {
        key.decode(): value.decode()
        for key, value in (await f.redis.hgetall(f.key + ":reservations")).items()
    }
    guard.durable_json(
        f.args.goal_dir / "primary/disposable-owner-monthly-authority.private.json",
        {
            "raw_after_real_settlement_usd": raw_monthly,
            "observed_after_real_settlement_nusd": str(observed_nusd),
            "predecessor_admitted_floor_nusd": binding["historical_floor_nusd"],
            "fresh_settled_cost_nusd": sum(
                row["amount_nusd"] for row in summary["accounting"]["calls"]
            ),
            "verified_owner_floor_nusd": verified_floor,
            "required_next_admission_floor_nusd": max(372_549_812, verified_floor),
            "fresh_calls": summary["accounting"]["calls"],
            "inherited_calls": summary["accounting"]["inherited_calls"],
            "aggregate_reserved_or_spent_nusd": summary["accounting"]["reserved_or_spent_nusd"],
            "retained_reservations": held,
            "monthly_ttl": await f.redis.ttl(f.key),
            "reservations_ttl": await f.redis.ttl(f.key + ":reservations"),
        },
    )
    return summary


def refresh_known_authorization(f, monkeypatch):
    approved = json.loads(f.known_authorization.read_text())
    approved["initial_predecessor_journal_sha256"] = file_hash(f.initial / "goal.sqlite")
    f.known_authorization.write_text(json.dumps(approved))
    monkeypatch.setattr(
        guard,
        "KNOWN_COST_AUTHORIZATION_SHA256",
        file_hash(f.known_authorization),
        raising=False,
    )


async def prepare_known_cost_fixture(f, monkeypatch):
    await guard.run(f.args)
    f.initial = f.args.goal_dir
    f.initial_summary = await stop_with_known_protocol_cost(f, monkeypatch)
    f.initial_bytes = (f.initial / "goal.sqlite").read_bytes()
    f.initial_anchor = (
        f.root
        / Path(guard.GOAL_ANCHOR).parent
        / ("guarded-counted-successor-" + file_hash(f.authorization) + ".json")
    )
    f.initial_anchor_bytes = f.initial_anchor.read_bytes()
    f.known_authorization = f.root / "known-cost-authorization.private.json"
    f.known_authorization.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "Finish unchanged full original live tests after verified protocol fixes",
                "user_safety_choice": "Finish original live tests",
                "initial_predecessor_goal": "/evidence/successor",
                "initial_predecessor_journal_sha256": file_hash(f.initial / "goal.sqlite"),
                "original_goal": "/evidence/predecessor",
                "original_journal_sha256": file_hash(f.predecessor / "goal.sqlite"),
                "prior_authorization_sha256": file_hash(f.authorization),
                "inherited_primary_requests_at_authorization": (
                    f.initial_summary["accounting"]["stages"]["primary"]["requests"]
                ),
                "expected_frozen_contract_sha256": guard.FROZEN[guard.GOLD],
                "preserve_all_predecessor_charges_and_reservations": True,
                "original_case_and_request_limits_remain": True,
                "request_caps": {
                    "primary": 720,
                    "shadow": 6 * f.selected,
                    "load": 66,
                    "smoke": 9,
                },
                "monthly_cutoff_usd_remains": "2",
                "minimum_verified_monthly_authority_nusd": 372_549_812,
                "retained_original_reservations": HELD,
                "stop_on_any_new_financial_uncertainty": True,
                "deploy_or_alias_promotion_authorized": False,
            }
        )
    )
    refresh_known_authorization(f, monkeypatch)
    f.args.action = "admit"
    f.args.goal_dir = f.root / "known-cost-first"
    f.args.predecessor_goal = f.initial
    f.args.successor_authorization = f.known_authorization
    return f


@pytest.fixture
async def known_cost_fixture(successor_fixture, monkeypatch):
    return await prepare_known_cost_fixture(successor_fixture, monkeypatch)


async def test_known_cost_successor_flattens_26_plus_fresh_one_and_denies_second_child(
    known_cost_fixture, record_property
):
    f = known_cost_fixture
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    expected = f.old.snapshot()["calls"] + f.initial_summary["accounting"]["calls"]
    assert budget.snapshot()["inherited_calls"] == expected
    assert [row["id"] for row in expected] == list(range(1, 28))
    assert budget.snapshot()["stages"]["primary"]["requests"] == 27
    assert budget.snapshot()["reserved_or_spent_nusd"] == 1_219_484
    assert binding["historical_floor_nusd"] == 372_549_812
    assert binding["successor"]["retained_reservations"] == HELD
    assert binding["successor"]["authorization_sha256"] == file_hash(f.known_authorization)
    assert all(
        budget.request_cap(stage) == cap
        for stage, cap in {"primary": 720, "shadow": 6 * f.selected, "load": 66, "smoke": 9}.items()
    )
    record_property("known_cost_flattened_binding", str(f.args.goal_dir / "goal-binding.json"))
    f.args.goal_dir = f.root / "known-cost-forbidden-fork"
    with pytest.raises((ValueError, FileExistsError)):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (f.initial / "goal.sqlite").read_bytes() == f.initial_bytes
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    assert f.initial_anchor.read_bytes() == f.initial_anchor_bytes
    assert (f.root / guard.GOAL_ANCHOR).read_bytes() == f.anchor_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == {
        k.encode(): v.encode() for k, v in HELD.items()
    }


@pytest.mark.parametrize(
    "fault",
    [
        "foreign",
        "ancestor_sha",
        "inherited_row",
        "request_cap",
        "cost_cap",
        "floor",
        "lower_hold",
        "missing_hold",
        "foreign_hold",
        "grant_hold",
        "fresh_failed",
        "fresh_uncertain",
        "normal_uncertain",
        "normal_held",
        "empty_fresh",
        "phase",
        "own_anchor",
        "raw_evidence",
        "protocol_evidence",
        "substituted_grant",
        "original_binding",
    ],
)
async def test_known_cost_successor_denies_financial_or_ancestry_drift_before_transport(
    known_cost_fixture, monkeypatch, fault
):
    f = known_cost_fixture
    initial_binding = json.loads((f.initial / "goal-binding.json").read_text())
    budget = VerificationBudget(
        f.initial / "goal.sqlite", binding=initial_binding["binding_sha256"]
    )
    ticket = f.initial_summary["calls"][-1]["journal_ticket"]
    if fault == "foreign":
        f.args.predecessor_goal = f.root / "foreign"
    elif fault == "ancestor_sha":
        with f.old._connect() as db:
            db.execute("UPDATE calls SET amount=2 WHERE id=1")
    elif fault == "original_binding":
        artifact = f.predecessor / "goal-binding.json"
        value = json.loads(artifact.read_text())
        value["monthly_cutoff_nusd"] = 3_000_000_000
        artifact.write_text(json.dumps(value))
    elif fault in {
        "inherited_row",
        "request_cap",
        "cost_cap",
        "fresh_failed",
        "fresh_uncertain",
        "normal_uncertain",
        "normal_held",
        "empty_fresh",
        "phase",
    }:
        with budget._connect() as db:
            if fault == "inherited_row":
                db.execute("UPDATE inherited_calls SET amount=2 WHERE id=1")
            elif fault == "request_cap":
                db.execute("UPDATE stages SET request_cap=721 WHERE name='primary'")
            elif fault == "cost_cap":
                db.execute("UPDATE stages SET cost_cap=500000001 WHERE name='primary'")
            elif fault == "fresh_failed":
                db.execute("UPDATE calls SET status='failed', error='CancelledError'")
            elif fault == "fresh_uncertain":
                row = json.loads(db.execute("SELECT receipt FROM guard_receipts").fetchone()[0])
                row["status"] = "uncertain"
                db.execute("UPDATE guard_receipts SET receipt=?", (json.dumps(row),))
            elif fault in {"normal_uncertain", "normal_held"}:
                row = json.loads(db.execute("SELECT receipt FROM guard_normal").fetchone()[0])
                row["uncertain" if fault == "normal_uncertain" else "settled"] = (
                    fault == "normal_uncertain"
                )
                db.execute("UPDATE guard_normal SET receipt=?", (json.dumps(row),))
            elif fault == "empty_fresh":
                db.execute("DELETE FROM calls")
                db.execute("DELETE FROM guard_receipts")
            else:
                db.execute("UPDATE guard_runs SET status='complete'")
        refresh_known_authorization(f, monkeypatch)
    elif fault == "floor":
        await f.redis.set(f.key, "0.372549811")
    elif fault in {"lower_hold", "missing_hold", "foreign_hold"}:
        if fault == "lower_hold":
            await f.redis.hset(f.key + ":reservations", "old-held-a", "0.02")
        elif fault == "missing_hold":
            await f.redis.hdel(f.key + ":reservations", "old-held-a")
        else:
            await f.redis.hset(f.key + ":reservations", "new-uncertainty", "0.01")
    elif fault == "grant_hold":
        approved = json.loads(f.known_authorization.read_text())
        approved["retained_original_reservations"]["old-held-a"] = "0.02"
        f.known_authorization.write_text(json.dumps(approved))
        refresh_known_authorization(f, monkeypatch)
    elif fault == "own_anchor":
        value = json.loads(f.initial_anchor.read_text())
        value["goal_dir"] = str(f.root / "foreign")
        f.initial_anchor.write_text(json.dumps(value))
    elif fault == "raw_evidence":
        (f.initial / "primary" / f"response-{ticket:06d}.body").write_bytes(b"changed")
    elif fault == "protocol_evidence":
        (f.initial / "primary" / f"protocol-failure-{ticket:06d}.json").unlink()
    else:
        f.known_authorization.write_text(f.known_authorization.read_text() + " ")
    before_original = (f.predecessor / "goal.sqlite").read_bytes()
    before_initial = (f.initial / "goal.sqlite").read_bytes()
    admissions = len(f.admissions)
    with pytest.raises((ValueError, FileExistsError, FileNotFoundError)):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (f.predecessor / "goal.sqlite").read_bytes() == before_original
    assert (f.initial / "goal.sqlite").read_bytes() == before_initial
    if fault not in {"floor", "lower_hold", "missing_hold", "foreign_hold"}:
        assert len(f.admissions) == admissions


async def test_known_cost_descendant_counts_every_request_and_uses_new_socket_session(
    known_cost_fixture, monkeypatch, record_property
):
    from app import main
    from app.evaluation.trace_capture import capture_turn
    from app.services import analyst_loop, analyst_sessions
    from app.tests.test_analyst_contracts import ScriptedAdapter

    f = known_cost_fixture
    await guard.run(f.args)
    first_goal = f.args.goal_dir
    first_binding = json.loads((first_goal / "goal-binding.json").read_text())
    stopped = await stop_with_known_protocol_cost(f, monkeypatch, cost=0.000001, valid_first=True)
    observations = json.loads((first_goal / "primary/observations.json").read_text())
    committed = next(
        row
        for row in observations["observations"]
        if row["capture"]["turn"].get("model_calls", 0) > 0
        and row["response"].get("state_committed")
    )
    first_bytes = (first_goal / "goal.sqlite").read_bytes()
    f.args.action = "admit"
    f.args.predecessor_goal = first_goal
    f.args.goal_dir = f.root / "known-cost-second"
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    expected = stopped["accounting"]["inherited_calls"] + stopped["accounting"]["calls"]
    assert budget.snapshot()["inherited_calls"] == expected
    assert budget.snapshot()["stages"]["primary"]["requests"] == len(expected) > 27
    assert binding["historical_floor_nusd"] == (
        first_binding["historical_floor_nusd"]
        + sum(row["amount_nusd"] for row in stopped["accounting"]["calls"])
    )
    ledger = guard.MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}",
        historical_floor=str(binding["historical_floor_nusd"] / 1e9),
        retained=HELD,
    )
    protocol, sent = ScriptedAdapter(), []

    async def respond(request):
        data = json.loads(request.content)
        sent.append(data)
        content = await protocol.generate(
            system=data["messages"][0]["content"], user=data["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": f"descendant-socket-{len(sent)}",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": 0.000001},
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            },
        )

    session = guard.GuardedSession(
        admission=f.admissions[-1],
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode="primary",
        run_dir=f.args.goal_dir / "socket",
        provider_transport=httpx.MockTransport(respond),
    )
    assert session.subject_namespace == binding["binding_sha256"]
    assert session.subject_namespace != first_binding["binding_sha256"]
    case = next(row for row in f.cases if row["id"] == committed["case_id"])
    request_id = committed["request_id"]
    payload = {
        "question": case["question"],
        "season": "2025-26",
        "context": case.get("context", []),
        "turn_id": request_id,
        "expected_revision": 0,
    }
    original_begin = analyst_sessions.SessionTurn.__dict__["begin"]
    captures = []
    app = None

    async def captured_app(scope, receive, send):
        with capture_turn() as capture:
            assert app is not None
            await app(scope, receive, send)
            if scope["type"] == "http" and scope["path"] == "/analysis/query":
                captures.append(capture)

    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter("primary", None)
        )
        app = main.create_app()
        async with private_server(captured_app, lifespan="off") as url:
            async with httpx.AsyncClient(base_url=url) as http:
                fresh = await http.post(
                    "/analysis/query", json=payload, headers={"x-request-id": request_id}
                )
                count = len(sent)
                replay = await http.post(
                    "/analysis/query", json=payload, headers={"x-request-id": request_id}
                )
    assert analyst_sessions.SessionTurn.__dict__["begin"] is original_begin
    assert fresh.status_code == 200 and fresh.json()["llm_validated"] and count > 0
    assert captures[0]["turn"]["replayed"] is False
    assert replay.json() == fresh.json() and len(sent) == count
    assert fresh.json()["request_id"] == request_id
    session.validate_receipt_joins()
    assert (first_goal / "goal.sqlite").read_bytes() == first_bytes
    assert (f.initial / "goal.sqlite").read_bytes() == f.initial_bytes
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    evidence = session.run_dir / "descendant-socket-evidence.json"
    guard.durable_json(
        evidence,
        {
            "captures": captures,
            "receipts": session.receipts(),
            "accounting": budget.snapshot(),
            "subject_namespace": session.subject_namespace,
            "transmissions": len(sent),
        },
    )
    record_property("known_cost_descendant_socket_evidence", str(evidence))
    f.args.goal_dir = f.root / "known-cost-second-forbidden-fork"
    with pytest.raises((ValueError, FileExistsError)):
        await guard.run(f.args)


@pytest.mark.parametrize(
    "stage,cap", [("primary", 720), ("shadow", 48), ("load", 66), ("smoke", 9)]
)
async def test_known_cost_inherited_ceiling_denies_before_real_http_transport(
    successor_fixture, monkeypatch, record_property, stage, cap
):
    from app import main
    from app.evaluation.trace_capture import capture_turn
    from app.services import analyst_loop

    f = successor_fixture
    if stage == "shadow":
        cap = 6 * f.selected
    fill_original_stage(f, monkeypatch, stage, cap - 1 if stage == "primary" else cap)
    await prepare_known_cost_fixture(f, monkeypatch)
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    ledger = guard.MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}",
        historical_floor=str(binding["historical_floor_nusd"] / 1e9),
        retained=HELD,
    )
    sent = []

    async def respond(request):
        sent.append(request)
        raise AssertionError("Exhausted ancestral stage cap reached HTTP transport")

    session = guard.GuardedSession(
        admission=f.admissions[-1],
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode="primary",
        stage=stage,
        run_dir=f.args.goal_dir / "socket",
        provider_transport=httpx.MockTransport(respond),
    )
    case = f.cases[0]
    request_id = evaluation_request_id(guard.FROZEN[guard.GOLD], "primary", case["id"])
    payload = {
        "question": case["question"],
        "season": "2025-26",
        "context": case.get("context", []),
        "turn_id": request_id,
        "expected_revision": 0,
    }
    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter(stage, None)
        )
        app = main.create_app()
        async with private_server(app, lifespan="off") as url:
            async with httpx.AsyncClient(base_url=url) as http:
                with capture_turn() as capture:
                    response = await http.post(
                        "/analysis/query", json=payload, headers={"x-request-id": request_id}
                    )
    assert not sent and budget.snapshot()["stages"][stage]["requests"] == cap
    assert budget.snapshot()["stopped"]
    evidence = session.run_dir / "inherited-cap-socket-evidence.json"
    guard.durable_json(
        evidence,
        {
            "capture": capture,
            "response": response.json(),
            "accounting": budget.snapshot(),
            "provider_transmissions": len(sent),
        },
    )
    record_property("known_cost_inherited_cap_evidence", str(evidence))


@pytest.mark.parametrize("fault", ["missing_cost", "over_bound", "transport_failure"])
async def test_known_cost_grant_never_admits_after_actual_new_financial_uncertainty(
    known_cost_fixture, monkeypatch, fault
):
    f = known_cost_fixture
    await guard.run(f.args)
    stopped_goal = f.args.goal_dir
    original_session = guard.GuardedSession
    sent = []

    async def respond(request):
        sent.append(request)
        if fault == "transport_failure":
            raise httpx.ReadTimeout("disposable uncertain transmission", request=request)
        return httpx.Response(
            200,
            json={
                "id": "new-financial-uncertainty",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": None if fault == "missing_cost" else 0.02},
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            },
        )

    with monkeypatch.context() as transport:
        transport.setattr(
            guard,
            "GuardedSession",
            lambda **kwargs: original_session(
                **kwargs, provider_transport=httpx.MockTransport(respond)
            ),
        )
        f.args.action = "collect"
        with pytest.raises(ValueError):
            await guard.run(f.args)
    assert len(sent) == 1
    summary = json.loads((stopped_goal / "primary/execution-summary.json").read_text())
    assert summary["status"] == "failed"
    assert summary["accounting"]["calls"][0]["status"] == "failed"
    assert summary["calls"][0]["status"] == "uncertain"
    held_before = await f.redis.hgetall(f.key + ":reservations")
    assert len(held_before) == 3
    stopped_bytes = (stopped_goal / "goal.sqlite").read_bytes()
    f.args.action = "admit"
    f.args.predecessor_goal = stopped_goal
    f.args.goal_dir = f.root / "denied-after-financial-uncertainty"
    with pytest.raises(ValueError):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (stopped_goal / "goal.sqlite").read_bytes() == stopped_bytes
    assert (f.initial / "goal.sqlite").read_bytes() == f.initial_bytes
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == held_before


@pytest.mark.parametrize("fault", ["missing_flags", "wrong_pair", "source", "binding_artifact"])
async def test_known_cost_collection_requires_admitted_pair_and_current_source(
    known_cost_fixture, monkeypatch, fault
):
    f = known_cost_fixture
    await guard.run(f.args)
    f.args.action = "collect"
    if fault == "missing_flags":
        f.args.successor_authorization = f.args.predecessor_goal = None
    elif fault == "wrong_pair":
        f.args.predecessor_goal = f.predecessor
    elif fault == "binding_artifact":
        artifact = f.args.goal_dir / "goal-binding.json"
        changed = json.loads(artifact.read_text())
        changed["historical_floor_nusd"] -= 1
        artifact.write_text(json.dumps(changed))
    else:
        original_hash = guard.file_hash
        monkeypatch.setattr(
            guard,
            "file_hash",
            lambda path: "f" * 64 if Path(path) == Path(guard.__file__) else original_hash(path),
        )
    original_session = guard.GuardedSession
    sent = []

    async def forbidden(request):
        sent.append(request)
        raise AssertionError("Changed admitted pair/source reached provider HTTP")

    monkeypatch.setattr(
        guard,
        "GuardedSession",
        lambda **kwargs: original_session(
            **kwargs, provider_transport=httpx.MockTransport(forbidden)
        ),
    )
    with pytest.raises(ValueError):
        await guard.run(f.args)
    assert not sent


async def test_known_cost_socket_headroom_does_not_double_count_ancestral_spend_or_old_holds(
    successor_fixture, monkeypatch, record_property
):
    from app import main
    from app.services import analyst_loop
    from app.tests.test_analyst_contracts import ScriptedAdapter

    f = successor_fixture
    # This settled original charge is already within the read-only monthly floor.
    with f.old._connect() as db:
        db.execute("UPDATE calls SET amount=100000000 WHERE id=1")
        receipt = json.loads(
            db.execute("SELECT receipt FROM guard_receipts WHERE ticket=1").fetchone()[0]
        )
        receipt["cost_nusd"] = 100_000_000
        db.execute("UPDATE guard_receipts SET receipt=? WHERE ticket=1", (json.dumps(receipt),))
    refresh_disposable_authorization(f, monkeypatch)
    f.original_bytes = (f.predecessor / "goal.sqlite").read_bytes()
    await f.redis.set(f.key, "1.9")
    await prepare_known_cost_fixture(f, monkeypatch)
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    assert binding["historical_floor_nusd"] == 1_900_042_130
    budget = VerificationBudget(f.args.goal_dir / "goal.sqlite", binding=binding["binding_sha256"])
    assert budget.snapshot()["reserved_or_spent_nusd"] > 100_000_000
    ledger = guard.MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}", historical_floor="1.900042130", retained=HELD
    )
    protocol, sent = ScriptedAdapter(), []

    async def respond(request):
        data = json.loads(request.content)
        sent.append(data)
        content = await protocol.generate(
            system=data["messages"][0]["content"], user=data["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": f"headroom-generation-{len(sent)}",
                "model": MODEL,
                "provider": "Morph",
                "usage": {"cost": 0.000001},
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            },
        )

    session = guard.GuardedSession(
        admission=f.admissions[-1],
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode="primary",
        run_dir=f.args.goal_dir / "socket",
        provider_transport=httpx.MockTransport(respond),
    )
    case = f.cases[0]
    request_id = evaluation_request_id(guard.FROZEN[guard.GOLD], "primary", case["id"])
    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter("primary", None)
        )
        app = main.create_app()
        async with private_server(app, lifespan="off") as url:
            async with httpx.AsyncClient(base_url=url) as http:
                response = await http.post(
                    "/analysis/query",
                    json={
                        "question": case["question"],
                        "season": "2025-26",
                        "context": case.get("context", []),
                        "turn_id": request_id,
                        "expected_revision": 0,
                    },
                    headers={"x-request-id": request_id},
                )
    assert response.status_code == 200 and response.json()["llm_validated"] and sent
    session.validate_receipt_joins()
    assert not budget.snapshot()["stopped"]
    assert await f.redis.hgetall(f.key + ":reservations") == {
        k.encode(): v.encode() for k, v in HELD.items()
    }
    evidence = session.run_dir / "headroom-socket-evidence.json"
    guard.durable_json(
        evidence,
        {
            "response": response.json(),
            "receipts": session.receipts(),
            "accounting": budget.snapshot(),
            "admitted_floor_nusd": binding["historical_floor_nusd"],
        },
    )
    record_property("known_cost_headroom_evidence", str(evidence))
