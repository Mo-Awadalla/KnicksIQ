"""Guarded orchestration HTTP/CLI scenarios, recorded before implementation.

Only synthetic metadata/completions and a fixture-owned Redis are permitted.
The existing real analyst HTTP route/collector must stop on admission, payload,
receipt, or interruption failures and keep case/ticket/monthly accounting joins.
Production Docker/source/index checks are not certified by these synthetic tests.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.release_runner import collect, file_hash
from app.evaluation.verification_adapter import MODEL
from app.evaluation.verification_budget import VerificationBudget
from app.services.release_evidence import evaluation_request_id
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from app.tests.test_release_evaluation import fixture_contract


def test_guarded_cli_denies_changed_gold_without_network(tmp_path):
    """The actual CLI rejects changed frozen inputs before opening any socket."""
    contract = tmp_path / "source-support-20261003/gold-review/frozen-expectations.json"
    contract.parent.mkdir(parents=True)
    contract.write_text('{"cases": []}')
    bootstrap = (
        "import socket,ssl,runpy,sys,httpx; "
        "socket.socket=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.argv=sys.argv[1:]; "
        "runpy.run_module('app.evaluation.guarded_release',run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            bootstrap,
            "guarded",
            "admit",
            "--mode",
            "primary",
            "--evidence-root",
            str(tmp_path),
            "--goal-dir",
            str(tmp_path / "goal"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["status"] == "denied_or_stopped"
    assert "network forbidden" not in result.stderr
    assert not (tmp_path / "goal" / "goal.sqlite").exists()


@pytest.mark.parametrize("mode", ["primary", "shadow"])
@pytest.mark.parametrize(
    "scenario",
    [
        "http_failure",
        "interruption",
        "wrong_provider",
        "missing_cost",
        "overbound",
        "provider_overbound",
        "provider_overbound_malformed",
        "invalid_action",
        "uncounted",
    ],
)
async def test_guarded_original_cohort_failure_joins_and_retains(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    mode,
    scenario,
    record_property,  # noqa: F811
):
    from app.api.analysis import _sample_shadow
    from app.evaluation.guarded_release import GuardedSession, MonthlyLedger

    settings = get_settings()
    for name, value in {
        "test_mode": False,
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary" if mode == "primary" else "shadow",
        "analysis_shadow_sample_rate": 0.1,
        "openrouter_monthly_cutoff_usd": 2.0,
        "rag_qdrant_enabled": False,
        "sentry_dsn": "",
        "ai_chat_model": MODEL,
        "analyst_call_reservation_usd": 0.01,
    }.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.0722179")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(fixture_contract()))
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "owner": "synthetic",
                "approved_at": "2026-01-01",
                "expectations_sha256": file_hash(contract),
            }
        )
    )
    shadow_ids = [
        evaluation_request_id(file_hash(contract), "shadow", c["id"])
        for c in fixture_contract()["cases"]
    ]
    journal = tmp_path / "goal.sqlite"
    VerificationBudget.create(
        journal,
        binding="synthetic",
        shadow_selected=sum(_sample_shadow(identity, 0.1) for identity in shadow_ids),
    )
    budget = VerificationBudget(journal, binding="synthetic")
    with budget._connect() as db:
        db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
        db.execute(
            "INSERT INTO guard_goal VALUES (?)",
            (json.dumps({"historical_floor_nusd": 72_217_900}),),
        )
    seen = []
    ledger = MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179")

    class SyntheticAdmission:
        contract_sha256 = file_hash(contract)
        cases = fixture_contract()["cases"]

        async def verify_environment(self, identity):
            assert len(identity["request_ids"]) == 120
            await ledger.read()

        async def verify_request(self, payload, owned):
            await ledger.read(owned)
            if scenario == "overbound":
                return {
                    "bound_nusd": 20_000_000,
                    "route": "morph/fp8",
                    "provider": "Morph",
                    "metadata_sha256": "synthetic",
                }
            return {
                "bound_nusd": 1_000_000,
                "route": "morph/fp8",
                "provider": "Morph",
                "metadata_sha256": "synthetic",
            }

    async def respond(request):
        seen.append(json.loads(request.content))
        if scenario == "interruption":
            raise httpx.ReadTimeout("synthetic interruption after transmission", request=request)
        if scenario == "http_failure":
            return httpx.Response(429)
        if scenario == "provider_overbound_malformed":
            identities = await local_redis.hkeys(key + ":reservations")
            assert len(identities) == 1
            await local_redis.hset(key + ":reservations", identities[0], "not-money")
        return httpx.Response(
            200,
            json={
                "id": "synthetic-generation",
                "model": MODEL,
                "provider": "Foreign" if scenario == "wrong_provider" else "Morph",
                "usage": {}
                if scenario == "missing_cost"
                else {"cost": 0.05 if scenario.startswith("provider_overbound") else 0},
                "choices": [
                    {
                        "message": {
                            "content": "{}"
                            if scenario == "invalid_action"
                            else "malformed analyst content"
                        }
                    }
                ],
            },
        )

    session = GuardedSession(
        admission=SyntheticAdmission(),
        budget=budget,
        ledger=ledger,
        api_key="synthetic",
        mode=mode,
        run_dir=tmp_path / "run",
        provider_transport=httpx.MockTransport(respond),
    )
    output = tmp_path / "observations.json"
    with session.installed():
        if scenario == "uncounted":
            from app.services.report_llm import OpenAICompatibleLLMAdapter

            with pytest.raises(RuntimeError):
                await OpenAICompatibleLLMAdapter(
                    base_url="https://openrouter.ai/api/v1", api_key="synthetic", model=MODEL
                ).generate(system="x", user="x")
        else:
            try:
                await collect(contract, approval, output, mode, execution=session.execution)
            except Exception:
                pass
    snapshot = budget.snapshot()
    rows = session.receipts()
    if scenario in {"overbound", "uncounted"}:
        assert not seen and not rows
    else:
        assert len(seen) == 1 and len(rows) == 1
        assert snapshot["stages"][mode]["requests"] == 1
        assert rows[0]["journal_ticket"] == snapshot["calls"][0]["id"]
        assert rows[0]["request_id"] == evaluation_request_id(
            file_hash(contract), mode, rows[0]["case_id"]
        )
        assert rows[0]["model"] == MODEL
        assert rows[0]["status"] == ("settled" if scenario == "invalid_action" else "uncertain")
        assert await local_redis.hlen(key + ":reservations") == (
            0 if scenario == "invalid_action" else 1
        )
        if scenario == "invalid_action":
            assert float(await local_redis.get(key)) == pytest.approx(0.0722179)
        else:
            assert float(await local_redis.get(key)) > 0.0722179
        assert await local_redis.ttl(key) == -1
        if scenario == "provider_overbound":
            assert rows[0]["reported_cost_nusd"] == 50_000_000
            assert snapshot["calls"][0]["amount_nusd"] == 50_000_000
            assert Decimal((await local_redis.get(key)).decode()) >= Decimal("0.1222179")
            assert (
                float(
                    await local_redis.hget(key + ":reservations", rows[0]["normal_reservation_id"])
                )
                >= 0.05
            )
        if scenario == "provider_overbound_malformed":
            assert rows[0]["reported_cost_nusd"] == 50_000_000
            assert snapshot["calls"][0]["amount_nusd"] == 50_000_000
            assert (
                await local_redis.hget(key + ":reservations", rows[0]["normal_reservation_id"])
                == b"not-money"
            )
            assert Decimal((await local_redis.get(key)).decode()) < Decimal("0.1222179")
    assert session.execution.failure
    assert snapshot["stopped"]
    if output.exists():
        artifact = json.loads(output.read_text())
        assert artifact["status"] == "failed"
        assert artifact["paid_requests"] == len(seen)
        if mode == "shadow":
            assert artifact["shadow_selected_count"] == sum(
                _sample_shadow(identity, 0.1) for identity in shadow_ids
            )
    artifact_path = tmp_path / "guarded-failure.json"
    artifact_path.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "mode": mode,
                "calls": rows,
                "journal": snapshot,
                "live_completions": 0,
            },
            indent=2,
        )
    )
    record_property("guarded_failure_artifact", str(artifact_path))


@pytest.mark.parametrize("fault", ["missing", "expiry", "foreign", "floor", "cutoff", "month"])
async def test_guarded_admission_denies_unreconciled_monthly_ledger(local_redis, tmp_path, fault):  # noqa: F811
    from app.evaluation.guarded_release import MonthlyLedger

    month = f"{datetime.now(UTC):%Y-%m}"
    key = "ai-budget:" + month
    if fault != "missing":
        await local_redis.set(key, "0.0722179")
    if fault == "expiry":
        await local_redis.expire(key, 3600)
    elif fault == "foreign":
        await local_redis.hset(key + ":reservations", "foreign", "0.01")
    elif fault == "floor":
        await local_redis.set(key, "0")
    elif fault == "cutoff":
        await local_redis.set(key, "2")
    elif fault == "month":
        month = "2000-01"
    ledger = MonthlyLedger(month=month, historical_floor="0.0722179")
    with pytest.raises(ValueError):
        await ledger.read()
    # Denial must not initialize, expire, settle, delete, or reset accounting.
    if fault == "missing":
        assert await local_redis.get(key) is None
    if fault == "foreign":
        assert await local_redis.hget(key + ":reservations", "foreign") == b"0.01"


async def test_guarded_successful_http_accounting_is_durable(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    from app.evaluation.guarded_release import GuardedSession, MonthlyLedger
    from app.services import analyst_loop
    from app.tests.test_analyst_contracts import ScriptedAdapter

    settings = get_settings()
    for name, value in {
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary",
        "openrouter_monthly_cutoff_usd": 2.0,
        "analyst_call_reservation_usd": 0.01,
    }.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.0722179")
    journal = tmp_path / "goal.sqlite"
    VerificationBudget.create(journal, binding="synthetic-success", shadow_selected=1)
    budget = VerificationBudget(journal, binding="synthetic-success")
    with budget._connect() as db:
        db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
        db.execute(
            "INSERT INTO guard_goal VALUES (?)",
            (json.dumps({"historical_floor_nusd": 72_217_900}),),
        )
    ledger = MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179")
    case = {
        "id": "synthetic-case",
        "question": "Tell me an interesting Jalen Brunson stat.",
        "context": [],
    }

    class SyntheticAdmission:
        contract_sha256 = "synthetic-gold"
        cases = [case]

        async def verify_environment(self, identity):
            await ledger.read()

        async def verify_request(self, payload, owned):
            await ledger.read(owned)
            return {
                "bound_nusd": 1_000_000,
                "route": "morph/fp8",
                "provider": "Morph",
                "metadata_sha256": "synthetic",
            }

    protocol = ScriptedAdapter()

    async def respond(request):
        payload = json.loads(request.content)
        raw = await protocol.generate(
            system=payload["messages"][0]["content"], user=payload["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": f"generation-{len(protocol.prompts)}",
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
        mode="primary",
        run_dir=tmp_path / "run",
        provider_transport=httpx.MockTransport(respond),
    )
    request_id = evaluation_request_id("synthetic-gold", "primary", case["id"])
    with session.installed():
        monkeypatch.setattr(
            analyst_loop, "get_llm_adapter", lambda: session.execution.adapter("primary", None)
        )
        from app.main import create_app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app()), base_url="https://test"
        ) as http:
            payload = {
                "question": case["question"],
                "season": "2025-26",
                "turn_id": request_id,
                "expected_revision": 0,
            }
            first = await http.post(
                "/analysis/query", json=payload, headers={"x-request-id": request_id}
            )
            replay = await http.post(
                "/analysis/query", json=payload, headers={"x-request-id": request_id}
            )
    assert first.status_code == 200 and first.json()["llm_validated"]
    assert replay.json() == first.json()
    calls = session.receipts()
    assert 2 <= len(calls) <= 6 and all(row["status"] == "settled" for row in calls)
    assert budget.snapshot()["stages"]["primary"]["requests"] == len(calls)
    assert await local_redis.hlen(key + ":reservations") == 0
    assert float(await local_redis.get(key)) == pytest.approx(0.0722179 + len(calls) * 0.000001)
    assert all(row["cost_nusd"] == 1000 and row["request_id"] == request_id for row in calls)
    artifact = tmp_path / "guarded-success.json"
    artifact.write_text(
        json.dumps({"calls": calls, "journal": budget.snapshot(), "live_completions": 0}, indent=2)
    )
    record_property("guarded_success_artifact", str(artifact))


async def test_collector_atomic_snapshot_failure_keeps_previous_http_evidence(
    client,
    monkeypatch,
    tmp_path,
):
    """Recorded before changing collector persistence: replace failure cannot truncate."""
    import os

    settings = get_settings()
    for name, value in {
        "ai_provider": "none",
        "redis_url": None,
        "rag_qdrant_enabled": False,
        "analyst_evidence_loop_enabled": True,
        "sentry_dsn": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(fixture_contract()))
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "owner": "synthetic",
                "approved_at": "2026-01-01",
                "expectations_sha256": file_hash(contract),
            }
        )
    )
    output = tmp_path / "observations.json"
    original = os.replace
    attempts = []

    def interrupted_replace(source, destination, *args, **kwargs):
        if Path(destination) == output:
            attempts.append(Path(source))
            # The old observation snapshot remains complete JSON until replace.
            assert json.loads(output.read_text())["status"] == "in_progress"
            raise OSError("synthetic durable snapshot interruption")
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", interrupted_replace)
    with pytest.raises(OSError):
        await collect(contract, approval, output, "disabled")
    assert attempts and all(not path.exists() for path in attempts)
    assert json.loads(output.read_text())["observations"] == []
