"""Synthetic HTTP evidence: actual SQL retrieval, model protocol, Redis commit/replay.

Failure cases: fabricated or detached search, mismatched scope/rank, missing
failed-tool capture, premature committed state, replay issuing another search,
or internal diagnostics escaping into the public response.
"""

import json
from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop, analyst_tools
from app.tests.test_analyst_contracts import ScriptedAdapter, local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats


@pytest.mark.parametrize("retrieval_failure", [False, True])
async def test_actual_search_trace_and_committed_replay(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    retrieval_failure,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    await local_redis.set(f"ai-budget:{datetime.now(UTC):%Y-%m}", 0)
    adapter = ScriptedAdapter()
    original = adapter.generate

    async def scripted(*, system, user):
        reply = json.loads(await original(system=system, user=user))
        if reply.get("action") == "call_tools":
            reply["tools"] = [
                {"name": "search_archive", "question": "BOS"},
                {"name": "get_player_stats", "question": "Jalen Brunson last 2 appearances"},
            ]
        return json.dumps(reply)

    monkeypatch.setattr(adapter, "generate", scripted)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    if retrieval_failure:

        async def unavailable(*args, **kwargs):
            raise ConnectionError("Synthetic retrieval failure")

        monkeypatch.setattr(analyst_tools, "search_archive_lexical", unavailable)
    payload = {
        "question": "What did Jalen Brunson average in his last 2 appearances?",
        "season": "2025-26",
        "turn_id": "captured-search-first-turn",
        "expected_revision": 0,
    }
    with capture_turn() as captured:
        response = await client.post("/analysis/query", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state_committed"] and body["citations"]
    assert captured["turn"]["state_committed"] is True
    assert captured["turn"]["revision"] == body["revision"]
    assert "capture" not in body and "searches" not in body
    search_result = next(t for t in captured["tools"] if t["call"]["name"] == "search_archive")
    if retrieval_failure:
        assert not captured["searches"]
        assert search_result["result"]["status"] == "dependency_failure"
    else:
        assert len(captured["searches"]) == 1
        search = captured["searches"][0]
        actual_ids = [e["evidence_id"] for e in search_result["result"]["evidence"]]
        assert actual_ids and search["candidate_evidence_ids"] == actual_ids
        assert search["returned_evidence_ids"] == actual_ids[:5]
        assert search["lexical_evidence_ids"] and not search["dense_evidence_ids"]
        assert all(e["release_id"] == "analytics-test" for e in search["evidence"])
    calls = len(adapter.prompts)
    with capture_turn() as replay_capture:
        replay = await client.post("/analysis/query", json=payload)
    assert replay.json() == body and len(adapter.prompts) == calls
    assert not replay_capture["searches"] and not replay_capture["tools"]
    assert replay_capture["turn"]["replayed"]
    artifact = tmp_path / "trace-http.json"
    artifact.write_text(
        json.dumps({"response": body, "capture": captured, "replay": replay_capture}, indent=2)
    )
    record_property("synthetic_trace_artifact", str(artifact))
