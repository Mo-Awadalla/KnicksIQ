"""No-paid, isolated tests of exact reconciliation and concurrent metadata checks."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from app.evaluation import guarded_release as guard
from app.evaluation.release_runner import file_hash
from app.evaluation.verification_adapter import MODEL
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_guarded_successor_http import (  # noqa: F401
    HELD,
    known_cost_fixture,
    successor_fixture,
)


def metadata_response(name) -> dict[str, Any]:
    values = {
        "key": {"usage": 0.1, "usage_monthly": 0.1, "is_free_tier": False},
        "credits": {"total_credits": 6, "total_usage": 0.1},
        "models": [
            {
                "id": MODEL,
                "canonical_slug": "deepseek/deepseek-v4.1-flash-20260910",
                "reasoning": {"mandatory": False},
                "supported_parameters": ["reasoning"],
                "architecture": {"output_modalities": ["text"]},
            }
        ],
        "endpoints": {
            "id": MODEL,
            "endpoints": [
                {
                    "tag": guard.ROUTE,
                    "model_id": MODEL,
                    "provider_name": guard.PROVIDER,
                    "quantization": "fp8",
                    "status": 0,
                    "pricing": {"prompt": "0.000000058", "completion": "0.00000045"},
                }
            ],
        },
    }
    return {"data": values[name]}


@pytest.mark.parametrize("route_kind", ["historical", "atlas"])
@pytest.mark.parametrize(
    "fault",
    [None, "http", "malformed", "unhealthy", "cancel", "provider", "quantization", "pricing"],
)
async def test_all_four_metadata_snapshots_are_current_concurrent_and_fail_closed(
    tmp_path, monkeypatch, fault, route_kind
):
    started, finished, cancelled = [], [], []
    barrier = asyncio.Event()

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"follow_redirects": False, "timeout": 10, "trust_env": False}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            name = url.rsplit("/", 1)[-1]
            started.append(name)
            if len(started) == 4:
                barrier.set()
            try:
                await barrier.wait()
                if fault == "cancel":
                    await asyncio.Event().wait()
                body = metadata_response(name)
                if name == "endpoints":
                    endpoint = cast(dict[str, Any], body["data"])["endpoints"][0]
                    if route_kind == "atlas":
                        endpoint.update(tag=guard.ATLAS_ROUTE, provider_name=guard.ATLAS_PROVIDER)
                    if fault == "provider":
                        endpoint["provider_name"] = "foreign"
                    if fault == "quantization":
                        endpoint["quantization"] = "foreign"
                    if fault == "pricing":
                        endpoint["pricing"]["foreign_charge"] = "1"
                if fault == "malformed" and name == "key":
                    body["data"] = []
                if fault == "unhealthy" and name == "endpoints":
                    routes = cast(dict[str, Any], body["data"])
                    routes["endpoints"][0]["status"] = -2
                finished.append(name)
                return httpx.Response(
                    503 if fault == "http" and name == "key" else 200,
                    json=body,
                    request=httpx.Request("GET", url),
                )
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

    monkeypatch.setattr(guard.httpx, "AsyncClient", Client)
    admission = object.__new__(guard.Admission)
    admission.route, admission.provider = (
        (guard.ROUTE, guard.PROVIDER)
        if route_kind == "historical"
        else (guard.ATLAS_ROUTE, guard.ATLAS_PROVIDER)
    )
    admission.route_authorization_sha256 = (
        None if route_kind == "historical" else guard.ATLAS_AUTHORIZATION_SHA256
    )
    admission.api_key = "synthetic-noncredential"
    admission.artifact_dir = tmp_path
    admission.metadata_count = 0
    task = asyncio.create_task(admission.provider_metadata())
    await asyncio.wait_for(barrier.wait(), timeout=1)
    if fault == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(cancelled) == 4
    elif fault:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            await task
        assert len(finished) == 4
    else:
        result = await task
        assert result["completion_requests"] == 0
        assert result["route"]["status"] == 0
        assert result["fetch_elapsed_ms"] >= 0
        assert len(finished) == 4
    assert set(started) == {"key", "credits", "models", "endpoints"}
    assert len(list(tmp_path.glob("provider-metadata-*.json"))) == (0 if fault else 1)


@pytest.fixture
async def reconciled_fixture(known_cost_fixture, monkeypatch):  # noqa: F811
    f = known_cost_fixture
    await guard.run(f.args)
    f.cancelled_goal = f.args.goal_dir
    original_session, original_admission = guard.GuardedSession, guard.Admission

    class ExactBoundAdmission(original_admission):
        async def verify_request(self, payload, owned):
            result = await super().verify_request(payload, owned)
            return {**result, "bound_nusd": 818_196}

    provider_entered = asyncio.Event()

    async def cancel(request) -> httpx.Response:
        provider_entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Synthetic never-returning provider resumed")

    original_wait = asyncio.wait_for

    async def accelerated_timeout(awaitable, timeout):
        pending = asyncio.ensure_future(awaitable)
        entered = asyncio.create_task(provider_entered.wait())
        try:
            done, _ = await asyncio.wait(
                (pending, entered), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if pending in done:
                return pending.result()
            return await original_wait(pending, min(timeout, 0.05) if entered in done else 0)
        finally:
            entered.cancel()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(entered, pending, return_exceptions=True)

    with monkeypatch.context() as transport:
        # Keep source preparation and admission deadlines intact. Accelerate
        # cancellation only after the mock provider has actually been entered.
        transport.setattr(
            analyst_loop,
            "asyncio",
            SimpleNamespace(wait_for=accelerated_timeout, timeout=asyncio.timeout),
        )
        transport.setattr(guard, "Admission", ExactBoundAdmission)
        transport.setattr(
            guard,
            "GuardedSession",
            lambda **kwargs: original_session(
                **kwargs, provider_transport=httpx.MockTransport(cancel)
            ),
        )
        f.args.action = "collect"
        with pytest.raises(ValueError):
            await guard.run(f.args)
    summary = json.loads((f.cancelled_goal / "primary/execution-summary.json").read_text())
    receipt = summary["calls"][0]
    assert receipt["journal_ticket"] == 28
    f.cancelled_bytes = (f.cancelled_goal / "goal.sqlite").read_bytes()
    f.held_before = await f.redis.hgetall(f.key + ":reservations")
    assert len(f.held_before) == 3
    await f.redis.set(f.key, "0.402549812")
    spec = {
        "schema_version": 1,
        "known_cost_authorization": "/evidence/"
        + f.known_authorization.relative_to(f.root).as_posix(),
        "known_cost_authorization_sha256": guard.KNOWN_COST_AUTHORIZATION_SHA256,
        "expected_frozen_contract_sha256": guard.FROZEN[guard.GOLD],
        "preserve_all_predecessor_charges_and_reservations": True,
        "stop_on_any_new_financial_uncertainty": True,
        "one_exclusive_successor_only": True,
        "journal_and_hold_mutation_authorized": False,
        "deploy_or_alias_promotion_authorized": False,
        "public_upload_authorized": False,
        "task_aggregate_hard_cap_usd": "6",
        "monthly_cutoff_usd_remains": "2",
        "request_caps": {"primary": 720, "shadow": 6 * f.selected, "load": 66, "smoke": 9},
        "minimum_verified_monthly_authority_nusd": 402_549_812,
        "predecessor_goal": "/evidence/" + f.cancelled_goal.relative_to(f.root).as_posix(),
        "predecessor_journal_sha256": file_hash(f.cancelled_goal / "goal.sqlite"),
        "reconciled_request": {
            "ticket": 28,
            "stage": "primary",
            "journal_status": "failed",
            "error_type": "CancelledError",
            "budget_charged_nusd": 818_196,
            "provider_cost_known": False,
            "provider_cost_nusd": None,
            "normal_hold_usd": "0.03",
            "payload_sha256": receipt["payload_sha256"],
            "normal_reservation_id": receipt["normal_reservation_id"],
        },
        "prior_counted_requests": 28,
        "retained_reservations": {**HELD, receipt["normal_reservation_id"]: "0.03"},
        "immutable_failure_evidence_sha256": {
            f"primary/{name}": file_hash(f.cancelled_goal / "primary" / name)
            for name in [
                "request-000028.json",
                "protocol-failure-000028.json",
                "execution-summary.json",
                "observations.json",
            ]
        },
    }
    f.reconciliation = f.root / "reconciliation.private.json"
    f.reconciliation.write_text(json.dumps(spec))
    monkeypatch.setattr(guard, "RECONCILIATION_AUTHORIZATION_SHA256", file_hash(f.reconciliation))
    f.args.action = "admit"
    f.args.goal_dir = f.root / "exact-reconciled-child"
    f.args.predecessor_goal = f.cancelled_goal
    f.args.successor_authorization = f.reconciliation
    f.spec = spec
    return f


async def test_reconciled_child_preserves_unknown_cost_full_bound_and_all_holds(reconciled_fixture):
    f = reconciled_fixture
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    lineage = binding["successor"]
    assert len(lineage["calls"]) == 28
    assert lineage["calls"][-1] == {
        "id": 28,
        "stage": "primary",
        "amount_nusd": 818_196,
        "status": "failed",
        "error": "CancelledError",
    }
    assert lineage["owner_budget_reconciliation"]["provider_cost_known"] is False
    assert lineage["receipts"][-1]["status"] == "uncertain"
    assert "cost_nusd" not in lineage["receipts"][-1]
    assert lineage["retained_reservations"] == f.spec["retained_reservations"]
    assert (f.cancelled_goal / "goal.sqlite").read_bytes() == f.cancelled_bytes
    assert (f.initial / "goal.sqlite").read_bytes() == f.initial_bytes
    assert (f.predecessor / "goal.sqlite").read_bytes() == f.original_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == f.held_before
    f.args.goal_dir = f.root / "duplicate-child"
    with pytest.raises(ValueError):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "old_grant",
        "auth_bytes",
        "unknown_cost",
        "bound",
        "ticket",
        "hold",
        "count",
        "caps",
        "floor",
        "journal",
        "receipt",
    ],
)
async def test_reconciliation_drift_denies_before_admission_and_preserves_evidence(
    reconciled_fixture, monkeypatch, fault
):
    f = reconciled_fixture
    if fault == "old_grant":
        f.args.successor_authorization = f.known_authorization
    elif fault == "journal":
        f.spec["predecessor_journal_sha256"] = "f" * 64
    elif fault == "unknown_cost":
        f.spec["reconciled_request"]["provider_cost_known"] = True
    elif fault == "bound":
        f.spec["reconciled_request"]["budget_charged_nusd"] -= 1
    elif fault == "ticket":
        f.spec["reconciled_request"]["ticket"] = 29
    elif fault == "hold":
        f.spec["retained_reservations"].pop(next(iter(HELD)))
    elif fault == "count":
        f.spec["prior_counted_requests"] = 27
    elif fault == "caps":
        f.spec["request_caps"]["primary"] += 1
    elif fault == "floor":
        f.spec["minimum_verified_monthly_authority_nusd"] -= 1
    elif fault == "receipt":
        f.spec["immutable_failure_evidence_sha256"]["primary/request-000028.json"] = "f" * 64
    if fault not in {"old_grant"}:
        f.reconciliation.write_text(json.dumps(f.spec) + (" " if fault == "auth_bytes" else ""))
        if fault != "auth_bytes":
            monkeypatch.setattr(
                guard, "RECONCILIATION_AUTHORIZATION_SHA256", file_hash(f.reconciliation)
            )
    with pytest.raises(ValueError):
        await guard.run(f.args)
    assert not (f.args.goal_dir / "goal.sqlite").exists()
    assert (f.cancelled_goal / "goal.sqlite").read_bytes() == f.cancelled_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == f.held_before


@pytest.fixture
async def atlas_fixture(reconciled_fixture, monkeypatch):
    f = reconciled_fixture
    spec = {
        "schema_version": 1,
        "reconciliation_authorization": "/evidence/"
        + f.reconciliation.relative_to(f.root).as_posix(),
        "reconciliation_authorization_sha256": guard.RECONCILIATION_AUTHORIZATION_SHA256,
        "predecessor_goal": "/evidence/" + f.cancelled_goal.relative_to(f.root).as_posix(),
        "predecessor_journal_sha256": file_hash(f.cancelled_goal / "goal.sqlite"),
        "prior_route": guard.ROUTE,
        "prior_provider": guard.PROVIDER,
        "route": guard.ATLAS_ROUTE,
        "provider": guard.ATLAS_PROVIDER,
        "model": MODEL,
        "quantization": "fp8",
        "frozen_contract_sha256": guard.FROZEN[guard.GOLD],
        "task_aggregate_hard_cap_usd": "6",
        "monthly_cutoff_usd": "2",
        "request_caps": f.spec["request_caps"],
        "all28prior_requests_and_three_holds_preserved": True,
        "one_exclusive_successor_only": True,
        "stop_on_any_new_financial_uncertainty": True,
        "fresh_metadata_and_actual_byte_bounds_every_payload": True,
        "original_deadlines_and_quality_workload_gates_unchanged": True,
        "public_upload_merge_or_production_authorized": False,
        "budget_charged_ticket28_nusd": 818_196,
        "provider_cost_ticket28_known": False,
    }
    f.atlas = f.root / "atlas-approval.private.json"
    f.atlas.write_text(json.dumps(spec))
    f.atlas_spec = spec
    monkeypatch.setattr(guard, "ATLAS_AUTHORIZATION_SHA256", file_hash(f.atlas))
    f.args.successor_authorization = f.atlas
    f.args.goal_dir = f.root / "atlas-successor"
    return f


async def test_atlas_rebind_changes_only_current_route_and_preserves_historical_provenance(
    atlas_fixture,
):
    f = atlas_fixture
    original_grant = f.reconciliation.read_bytes()
    await guard.run(f.args)
    binding = json.loads((f.args.goal_dir / "goal-binding.json").read_text())
    assert binding["route"] == guard.ATLAS_ROUTE
    assert binding["successor"]["route_rebind"]["provider"] == guard.ATLAS_PROVIDER
    assert binding["successor"]["predecessor_binding"]["route"] == guard.ROUTE
    assert {x.get("route", guard.ROUTE) for x in binding["successor"]["receipts"]} == {guard.ROUTE}
    assert len(binding["successor"]["calls"]) == 28
    assert binding["successor"]["calls"][-1]["status"] == "failed"
    assert guard.admission_route(binding) == {
        "route": guard.ATLAS_ROUTE,
        "provider": guard.ATLAS_PROVIDER,
        "route_authorization_sha256": guard.ATLAS_AUTHORIZATION_SHA256,
    }
    assert (f.cancelled_goal / "goal.sqlite").read_bytes() == f.cancelled_bytes
    assert f.reconciliation.read_bytes() == original_grant
    assert await f.redis.hgetall(f.key + ":reservations") == f.held_before
    f.args.goal_dir = f.root / "duplicate-atlas"
    with pytest.raises(ValueError):
        await guard.run(f.args)


@pytest.mark.parametrize(
    "fault",
    ["route", "provider", "model", "cap", "floor", "hold", "settlement", "grant", "predecessor"],
)
async def test_atlas_rebind_denies_drift_before_goal_or_transmission(
    atlas_fixture, monkeypatch, fault
):
    f = atlas_fixture
    if fault == "route":
        f.atlas_spec["route"] = "unapproved/fp8"
    if fault == "provider":
        f.atlas_spec["provider"] = "unapproved"
    if fault == "model":
        f.atlas_spec["model"] = "unapproved"
    if fault == "cap":
        f.atlas_spec["request_caps"]["primary"] += 1
    if fault == "floor":
        f.atlas_spec["monthly_cutoff_usd"] = "6"
    if fault == "hold":
        f.atlas_spec["all28prior_requests_and_three_holds_preserved"] = False
    if fault == "settlement":
        f.atlas_spec["provider_cost_ticket28_known"] = True
    if fault == "grant":
        f.atlas_spec["reconciliation_authorization_sha256"] = "f" * 64
    if fault == "predecessor":
        f.atlas_spec["predecessor_goal"] = "/evidence/other"
    f.atlas.write_text(json.dumps(f.atlas_spec))
    monkeypatch.setattr(guard, "ATLAS_AUTHORIZATION_SHA256", file_hash(f.atlas))
    with pytest.raises(ValueError):
        await guard.run(f.args)
    assert not f.args.goal_dir.exists()
    assert (f.cancelled_goal / "goal.sqlite").read_bytes() == f.cancelled_bytes
    assert await f.redis.hgetall(f.key + ":reservations") == f.held_before


def test_admission_route_requires_exact_owner_rebind_before_any_private_file_read(tmp_path):
    with pytest.raises(ValueError):
        guard.Admission(
            evidence_root=tmp_path,
            artifact_dir=tmp_path,
            api_key="synthetic",
            ledger=guard.MonthlyLedger(month="2026-10", historical_floor="0.4"),
            route=guard.ATLAS_ROUTE,
            provider=guard.ATLAS_PROVIDER,
        )
