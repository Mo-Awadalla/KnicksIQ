"""The shadow trial never gates, delays or rewrites the client's facts."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

import pytest
from app.api.analysis import _sample_shadow
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services import analyst_provider
from app.tests.support.analyst_protocol import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.support.player_archive import _seed_release_stats

QUESTION = "What did Jalen Brunson average in his last 2 appearances?"
TURN = "shadow-isolation-turn"


def _payload(question: str = QUESTION, turn_id: str = TURN) -> dict[str, object]:
    return {
        "question": question,
        "season": "2025-26",
        "turn_id": turn_id,
        "expected_revision": 0,
    }


def _session_key(turn_id: str) -> str:
    token = hmac.new(
        get_settings().ip_hash_secret.encode(),
        ("analyst-session:" + turn_id).encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"analyst:{{{token}}}"


def _configure(monkeypatch, *, mode: str = "shadow", rate: float = 1.0) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", rate)


async def _seed_release() -> None:
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)


def _assert_delivered_facts(body: dict) -> None:
    assert body["citations"], body
    assert "25" in body["answer"], body
    assert body["route"] == "factual_fallback"
    assert body["llm_validated"] is False


async def test_committed_turn_exists_before_the_shadow_trial(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    """Facts reach the session before any provider call, so the trial cannot gate them."""
    _configure(monkeypatch)
    await _seed_release()
    observed: dict[str, object] = {}

    class RecordingAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            key = _session_key(TURN)
            observed["revision"] = await local_redis.hget(key, "revision")
            observed["turn"] = await local_redis.hget(key, f"turn:{TURN}")
            return await super().generate(system=system, user=user)

    adapter = RecordingAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    response = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-commit-first"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_delivered_facts(body)
    assert body["state_committed"] is True and body["revision"] == 1
    assert adapter.prompts, "the sampled trial must still run"
    assert observed["revision"] == b"1"
    assert observed["turn"] is not None


async def test_failed_shadow_trial_keeps_normal_delivery(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    """A private verification failure is not the client's outage."""
    _configure(monkeypatch)
    await _seed_release()
    calls = 0

    class FailingAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            nonlocal calls
            calls += 1
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: FailingAdapter())
    response = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-trial-failed"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_delivered_facts(body)
    assert body["degraded"] is False
    assert body["warnings"] == []
    assert body["state_committed"] is True and body["revision"] == 1
    assert calls, "the sampled trial must have attempted the provider"


async def test_shadow_trial_does_not_rewrite_the_committed_answer(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    """The delivered answer is the deterministic one, and replay returns it byte for byte."""
    _configure(monkeypatch)
    await _seed_release()
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    first = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-rewrite-first"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    _assert_delivered_facts(body)
    assert adapter.prompts, "the sampled trial must still run"
    calls = len(adapter.prompts)
    replay = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-rewrite-replay"}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == body
    assert len(adapter.prompts) == calls


async def test_unsampled_turn_runs_no_trial(client, local_redis, monkeypatch):  # noqa: F811
    _configure(monkeypatch, rate=0.0)
    await _seed_release()
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    response = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-unsampled"}
    )
    assert response.status_code == 200, response.text
    _assert_delivered_facts(response.json())
    assert adapter.prompts == []


async def test_stateless_request_runs_no_trial(client, local_redis, monkeypatch):  # noqa: F811
    _configure(monkeypatch)
    await _seed_release()
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    payload = {"question": QUESTION, "season": "2025-26"}
    response = await client.post(
        "/analysis/query", json=payload, headers={"x-request-id": "shadow-stateless"}
    )
    assert response.status_code == 200, response.text
    _assert_delivered_facts(response.json())
    assert adapter.prompts == []


async def test_primary_model_failure_is_still_degraded(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    """Isolation belongs to the shadow mode only; the primary path reports its real failure."""
    _configure(monkeypatch, mode="llm_primary")
    await _seed_release()

    class FailingAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: FailingAdapter())
    response = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "primary-failure"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    assert body["llm_validated"] is False
    assert body["warnings"]


async def test_private_trial_still_settles_its_budget(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
):
    """An unknown provider cost stays charged after the response was already sent."""
    _configure(monkeypatch)
    await _seed_release()

    class UnknownCostAdapter(ScriptedAdapter):
        async def generate(self, *, system, user):
            self.last_metadata = {"usage": {}, "provider": "protocol-fixture"}
            return await super().generate(system=system, user=user)

    adapter = UnknownCostAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    response = await client.post(
        "/analysis/query", json=_payload(), headers={"x-request-id": "shadow-budget"}
    )
    assert response.status_code == 200, response.text
    assert adapter.prompts
    spent = await local_redis.get(f"ai-budget:{datetime.now(UTC):%Y-%m}")
    assert spent is not None and float(spent) > 0
    assert float(spent) == pytest.approx(
        len(adapter.prompts) * get_settings().analyst_call_reservation_usd
    )


async def test_private_verification_records_content_free_diagnostics(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    caplog,
):
    """The trial's value is diagnostics; they stay private and never carry answer content."""
    _configure(monkeypatch)
    await _seed_release()
    adapter = ScriptedAdapter()
    monkeypatch.setattr(analyst_provider, "get_llm_adapter", lambda: adapter)
    with caplog.at_level(logging.INFO, logger="app.api.analysis_shadow"):
        response = await client.post(
            "/analysis/query",
            json=_payload(turn_id="shadow-diagnostics"),
            headers={"x-request-id": "shadow-diagnostics"},
        )
    assert response.status_code == 200, response.text
    assert adapter.prompts
    records = [r for r in caplog.records if r.getMessage() == "analyst_shadow_verification"]
    assert records, [r.getMessage() for r in caplog.records]
    record = records[0]
    assert record.sampled is True
    assert record.validated is True
    assert record.outcome == "answer"
    assert record.model_calls >= 2 and record.data_version == "analytics-test"
    assert "Brunson" not in caplog.text and "25.0 points" not in caplog.text


def _plain_bucket(request_id: str) -> float:
    """The draw a caller could compute from its own request id alone."""
    return int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:4], "big") / (2**32 - 1)


def test_shadow_sampling_cannot_be_steered_by_the_request_id(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ip_hash_secret", "server-secret-alpha")
    rate = 0.1
    # Ids a caller can enumerate offline into the sampled bucket of a request-id-only draw.
    forced = [f"steer-{i}" for i in range(4000) if _plain_bucket(f"steer-{i}") < rate]
    assert len(forced) > 200
    sampled = [rid for rid in forced if _sample_shadow(rid, rate)]
    assert sampled == [rid for rid in forced if _sample_shadow(rid, rate)]
    assert 0 < len(sampled) < len(forced) * 0.25
    monkeypatch.setattr(settings, "ip_hash_secret", "server-secret-beta")
    rotated = [rid for rid in forced if _sample_shadow(rid, rate)]
    assert rotated != sampled
    population = [f"population-{i}" for i in range(2000)]
    share = sum(_sample_shadow(rid, rate) for rid in population) / len(population)
    assert 0.05 < share < 0.15
    assert not any(_sample_shadow(rid, 0.0) for rid in population)
    assert all(_sample_shadow(rid, 1.0) for rid in population)
