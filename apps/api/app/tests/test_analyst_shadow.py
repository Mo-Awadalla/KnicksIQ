"""HTTP shadow delivery, sampling and replay with synthetic SQL and real Redis."""

import json
from datetime import UTC, datetime

import pytest
from app.api.analysis import _sample_shadow
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services import analyst_loop
from app.tests.test_analyst_contracts import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats


@pytest.mark.parametrize(
    ("mode", "rate", "sampled", "budget", "malformed", "calls"),
    [
        ("shadow", 0.0, True, True, False, False),
        ("shadow", 1.0, False, True, False, True),
        ("shadow", 0.1, True, True, False, True),
        ("shadow", 0.1, False, True, False, False),
        ("llm_primary", 0.0, False, True, False, True),
        ("shadow", 1.0, True, False, False, False),
        ("shadow", 1.0, True, True, True, True),
    ],
)
async def test_evidence_loop_shadow_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    mode,
    rate,
    sampled,
    budget,
    malformed,
    calls,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", rate)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    if budget:
        await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    adapter = ScriptedAdapter()
    original_generate = adapter.generate

    async def player_generate(*, system, user):
        result = json.loads(await original_generate(system=system, user=user))
        if result.get("action") == "call_tools":
            result["tools"][0]["name"] = "get_player_stats"
        return json.dumps(result)

    monkeypatch.setattr(adapter, "generate", player_generate)
    if malformed:

        async def invalid_generate(**kwargs):
            adapter.prompts.append(kwargs)
            return '{"action":"invented"}'

        monkeypatch.setattr(adapter, "generate", invalid_generate)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    request_id = next(
        f"sampling-{i}" for i in range(1000) if _sample_shadow(f"sampling-{i}", 0.1) == sampled
    )
    payload = {
        "question": "What did Jalen Brunson average in his last 2 appearances?",
        "season": "2025-26",
        "turn_id": "shadow-sampling-first-turn",
        "expected_revision": 0,
    }
    response = await client.post(
        "/analysis/query", json=payload, headers={"x-request-id": request_id}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert bool(adapter.prompts) == calls
    assert body["answer"] and "25" in body["answer"] and body["citations"]
    assert body["state_committed"] and body["revision"] == 1
    assert body["llm_validated"] == (mode == "llm_primary")
    count = len(adapter.prompts)
    replay = await client.post(
        "/analysis/query", json=payload, headers={"x-request-id": "different-replay-request"}
    )
    assert replay.status_code == 200 and replay.json() == body
    assert len(adapter.prompts) == count
    conflict = await client.post(
        "/analysis/query", json={**payload, "question": "Different question"}
    )
    assert conflict.status_code == 409
    assert len(adapter.prompts) == count
