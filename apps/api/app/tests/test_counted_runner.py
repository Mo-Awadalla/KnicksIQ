"""Pre-implementation runner integration failure matrix.

A swallowed provider failure must stop the cohort even when fallback returns 200;
preflight rejection must produce zero provider traffic; every request ID and
shadow membership must be fixed before responses; partial evidence and cumulative
spend must survive; global adapter factories must be restored after failure.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest
from app.api.analysis import _sample_shadow
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.release_runner import collect, file_hash
from app.evaluation.verification_budget import VerificationBudget
from app.services import analyst_loop
from app.services.release_evidence import evaluation_request_id
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats
from app.tests.test_release_evaluation import fixture_contract


@pytest.mark.parametrize("preflight_failure", [False, True])
@pytest.mark.parametrize("mode", ["primary", "shadow"])
async def test_counted_runner_stops_and_retains_failed_turn(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    preflight_failure,
    mode,
):
    from app.evaluation.verification_adapter import CountedRun

    settings = get_settings()
    for name, value in {
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary" if mode == "primary" else "shadow",
        "analysis_shadow_sample_rate": 0.1,
        "openrouter_monthly_cutoff_usd": 2.0,
        "rag_qdrant_enabled": False,
        "sentry_dsn": "",
        "ai_chat_model": "deepseek/deepseek-v4.1-flash",
    }.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
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
    journal = tmp_path / "goal.sqlite"
    ids = [
        evaluation_request_id(file_hash(contract), "shadow", c["id"])
        for c in fixture_contract()["cases"]
    ]
    selected = sum(_sample_shadow(identity, 0.1) for identity in ids)
    VerificationBudget.create(journal, binding="synthetic", shadow_selected=selected)
    budget = VerificationBudget(journal, binding="synthetic")
    seen = []
    checked = []

    async def preflight(identity):
        checked.append(identity)
        assert len(identity["request_ids"]) == 120
        assert identity["expectations_sha256"] == file_hash(contract)
        if preflight_failure:
            raise ValueError("unavailable verified monthly allowance")

    async def request_bound(payload):
        return 10_000_000

    def response(request):
        seen.append(str(request.url))
        return httpx.Response(429)

    execution = CountedRun(
        api_key="synthetic",
        budget=budget,
        verify_environment=preflight,
        verify_request=request_bound,
        transport=httpx.MockTransport(response),
    )
    original = analyst_loop.get_llm_adapter
    output = tmp_path / "observations.json"
    with pytest.raises(ValueError):
        await collect(contract, approval, output, mode, execution=execution)
    assert analyst_loop.get_llm_adapter is original
    assert len(checked) >= 1
    if preflight_failure:
        assert not seen and not output.exists()
    else:
        artifact = json.loads(output.read_text())
        assert artifact["status"] == "failed"
        assert artifact["request_ids"] == [
            evaluation_request_id(file_hash(contract), mode, c["id"])
            for c in fixture_contract()["cases"]
        ]
        if mode == "primary":
            assert len(artifact["observations"]) == 1
        else:
            assert artifact["shadow_selected_count"] == selected
            for observation in artifact["observations"]:
                if not _sample_shadow(observation["request_id"], 0.1):
                    assert observation["capture"]["turn"]["model_calls"] == 0
        assert artifact["observations"][0]["http_status"] == 200
        assert artifact["paid_requests"] == 1
        assert artifact["accounting"]["stopped"]
        assert len(seen) == 1
