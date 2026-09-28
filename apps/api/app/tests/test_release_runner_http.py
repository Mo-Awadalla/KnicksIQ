"""Full fixed cohort through ASGI, without paid services or rate-limit changes.

Failures: a 120-case run exhausting a single synthetic client's daily quota;
missing source/config/approval bindings; overwriting prior evidence; and losing
partial artifacts on HTTP errors. Synthetic expectations are not release gold.
"""

import json

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.release_runner import collect, file_hash
from app.tests.test_player_intelligence import _seed_release_stats
from app.tests.test_release_evaluation import fixture_contract


async def test_disabled_cohort_uses_real_limits_and_keeps_bound_artifact(
    client, monkeypatch, tmp_path
):
    settings = get_settings()
    for name, value in {
        "test_mode": False,
        "db_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": "",
        "ai_provider": "disabled",
        "rag_qdrant_enabled": False,
        "analyst_evidence_loop_enabled": True,
        "analysis_answer_mode": "llm_primary",
        "sentry_dsn": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    contract = tmp_path / "synthetic-contract.json"
    contract.write_text(json.dumps(fixture_contract()))
    approval = tmp_path / "synthetic-owner.json"
    approval.write_text(
        json.dumps(
            {
                "owner": "synthetic fixture only",
                "approved_at": "2026-01-01",
                "expectations_sha256": file_hash(contract),
            }
        )
    )
    output = tmp_path / "observations.json"
    result = await collect(contract, approval, output, "disabled")
    assert len(result["observations"]) == 120
    assert result["approval_sha256"] == file_hash(approval)
    assert result["configuration"]["public_chat_rate_limit_per_day"] == 100
    assert result["configuration"]["public_chat_rate_limit_per_minute"] == 10
    assert result["configuration"]["test_mode"] is False
    assert result["paid_requests"] == 0
    assert all(o["http_status"] == 200 for o in result["observations"])
    assert len({o["synthetic_client"] for o in result["observations"]}) == 120
    assert all(o["capture"]["turn"].get("model_calls", 0) == 0 for o in result["observations"])
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        await collect(contract, approval, output, "disabled")
    assert output.read_bytes() == original
