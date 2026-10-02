"""HTTP/counting failure modes specified before changing verification caps."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.verification_adapter import MODEL, CountedVerificationAdapter
from app.evaluation.verification_budget import VerificationBudget
from app.services import analyst_loop
from app.tests.test_analyst_contracts import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats

ROOT = Path(__file__).resolve().parents[4]
DIRECTION = ROOT / "docs/release-evidence/implementation-20261001/confirmed-spending-direction.json"


def retain(tmp_path, name, data, record_property):
    root = Path(os.environ.get("KNICKSIQ_SPENDING_ARTIFACT_DIR", str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name + ".json")
    with path.open("x") as artifact:
        json.dump(data, artifact, indent=2)
        artifact.write("\n")
    record_property("spending_http_artifact", str(path))


async def test_owner_spending_direction_survives_counted_http_and_reopen(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,  # noqa: F811
):
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_monthly_cutoff_usd", 2.0)
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, 0)
    path = tmp_path / "journal.sqlite"
    VerificationBudget.create(path, binding="synthetic-spending-http", shadow_selected=1)
    budget = VerificationBudget(path, binding="synthetic-spending-http")
    budget.apply_spending_direction(DIRECTION)
    protocol = ScriptedAdapter()
    seen = []

    async def verify(payload):
        assert payload["model"] == MODEL
        assert float(await local_redis.get(key)) + 0.75 <= 2
        assert settings.openrouter_monthly_cutoff_usd == 2
        return 750_000_000

    async def respond(request):
        body = json.loads(request.content)
        raw = await protocol.generate(
            system=body["messages"][0]["content"], user=body["messages"][1]["content"]
        )
        seen.append({"model": body["model"], "cost_usd": 0.6})
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "provider": "synthetic",
                "usage": {"cost": 0.6},
                "choices": [{"message": {"content": raw}}],
            },
        )

    def factory():
        return CountedVerificationAdapter(
            api_key="synthetic",
            budget=budget,
            stage="primary",
            verify_request=verify,
            transport=httpx.MockTransport(respond),
        )

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", factory)
    payload = {
        "question": "Tell me an interesting Jalen Brunson stat.",
        "season": "2025-26",
        "turn_id": "spending-direction-http",
        "expected_revision": 0,
    }
    response = await client.post("/analysis/query", json=payload)
    body = response.json()
    snapshot = budget.snapshot()
    reopened = VerificationBudget(path, binding="synthetic-spending-http")
    replay = await client.post("/analysis/query", json=payload)
    ledger = float(await local_redis.get(key))
    retain(
        tmp_path,
        "authorized-http",
        {
            "response": body,
            "http_status": response.status_code,
            "journal": snapshot,
            "reopened_journal": reopened.snapshot(),
            "replay": replay.json(),
            "monthly_spent_or_reserved": ledger,
            "provider_requests": seen,
            "production_cutoff_setting": settings.openrouter_monthly_cutoff_usd,
            "live_completions": 0,
        },
        record_property,
    )
    assert response.status_code == 200 and body["state_committed"] and body["llm_validated"]
    assert 2 <= len(seen) <= 3
    assert snapshot["reserved_or_spent_nusd"] == len(seen) * 600_000_000 > 1_100_000_000
    assert snapshot["historical_dollar_caps_enforced"] is False
    assert (
        snapshot["spending_direction_sha256"] == hashlib.sha256(DIRECTION.read_bytes()).hexdigest()
    )
    assert reopened.snapshot() == snapshot
    assert replay.json() == body and budget.snapshot() == snapshot
    assert ledger == pytest.approx(len(seen) * 0.6) and settings.openrouter_monthly_cutoff_usd == 2


async def test_spending_direction_preserves_counted_failure_and_selected_ceiling(
    tmp_path, record_property
):
    path = tmp_path / "journal.sqlite"
    VerificationBudget.create(path, binding="synthetic-ceilings", shadow_selected=1)
    budget = VerificationBudget(path, binding="synthetic-ceilings")
    before = budget.snapshot()
    altered = tmp_path / "altered-direction.json"
    altered.write_text(DIRECTION.read_text() + "\n")
    with pytest.raises(ValueError):
        budget.apply_spending_direction(altered)
    assert budget.snapshot() == before
    budget.apply_spending_direction(DIRECTION)

    async def verify(_payload):
        return 600_000_000

    seen = []

    async def response(request):
        seen.append(str(request.url))
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "provider": "synthetic",
                "usage": {"cost": 0.4},
                "choices": [{"message": {"content": "synthetic completion"}}],
            },
        )

    adapter = CountedVerificationAdapter(
        api_key="synthetic",
        budget=budget,
        stage="shadow",
        verify_request=verify,
        transport=httpx.MockTransport(response),
    )
    results = await asyncio.gather(
        *(adapter.generate(system="synthetic", user="synthetic") for _ in range(7)),
        return_exceptions=True,
    )
    after = budget.snapshot()
    assert len(seen) == 6 and sum(isinstance(r, ValueError) for r in results) == 1
    assert after["stages"]["shadow"]["requests"] == 6
    assert after["reserved_or_spent_nusd"] == 2_400_000_000
    failed_adapter = CountedVerificationAdapter(
        api_key="synthetic",
        budget=budget,
        stage="primary",
        verify_request=verify,
        transport=httpx.MockTransport(lambda _r: httpx.Response(429)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await failed_adapter.generate(system="synthetic", user="synthetic")
    stopped = budget.snapshot()
    with pytest.raises(ValueError):
        budget.apply_spending_direction(DIRECTION)
    assert budget.snapshot() == stopped and stopped["stopped"]
    assert stopped["reserved_or_spent_nusd"] == 3_000_000_000
    assert budget.request_cap("smoke") == 9 and budget.request_cap("primary") == 720
    retain(
        tmp_path,
        "ceiling-and-failure",
        {
            "journal": stopped,
            "before": before,
            "after_six": after,
            "live_completions": 0,
        },
        record_property,
    )
