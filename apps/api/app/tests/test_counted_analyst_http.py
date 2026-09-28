"""Actual analyst HTTP path with a counted synthetic provider and local Redis.

Verify all nested generation/review requests share the journal; retain normal
monthly reservations, citations, committed state, and no-call replay. This is
protocol/infrastructure verification, not a live quality evaluation.
"""

import json
from datetime import UTC, datetime

import httpx
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.verification_adapter import MODEL, CountedVerificationAdapter
from app.evaluation.verification_budget import VerificationBudget
from app.services import analyst_loop
from app.tests.test_analyst_contracts import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats


async def test_counted_nested_calls_keep_monthly_budget_and_replay(
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
    VerificationBudget.create(path, binding="synthetic-http", shadow_selected=1)
    budget = VerificationBudget(path, binding="synthetic-http")
    protocol = ScriptedAdapter()

    async def verify(payload):
        assert float(await local_redis.get(key)) > 0  # normal reservation precedes transport
        assert settings.openrouter_monthly_cutoff_usd == 2
        return 10_000_000

    async def respond(request):
        body = json.loads(request.content)
        raw = await protocol.generate(
            system=body["messages"][0]["content"], user=body["messages"][1]["content"]
        )
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "provider": "synthetic",
                "usage": {"cost": 0},
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
        "turn_id": "counted-http-first-turn",
        "expected_revision": 0,
    }
    response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state_committed"] and body["citations"]
    calls = budget.snapshot()["stages"]["primary"]["requests"]
    assert 2 <= calls <= 6
    assert calls == len(protocol.prompts)
    assert float(await local_redis.get(key)) == 0
    replay = await client.post("/analysis/query", json=payload)
    assert replay.json() == body
    assert budget.snapshot()["stages"]["primary"]["requests"] == calls
    artifact = tmp_path / "counted-http.json"
    artifact.write_text(
        json.dumps(
            {
                "response": body,
                "journal": budget.snapshot(),
                "monthly_reserved_or_spent": float(await local_redis.get(key)),
            },
            indent=2,
        )
    )
    record_property("counted_http_artifact", str(artifact))
