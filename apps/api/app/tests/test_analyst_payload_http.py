"""Evidence packaging through HTTP/SQL/Redis, retaining exact protocol artifacts."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Evidence
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_player_intelligence import _seed_release_stats


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def configure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "llm_primary")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    monkeypatch.setattr(settings, "analyst_input_tokens", 8000)
    monkeypatch.setattr(settings, "analyst_evidence_tokens", 6000)
    return settings


async def exchange(client, redis, adapter, name, question):
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.125")
    payload = {
        "question": question,
        "turn_id": f"payload-regression-{name}",
        "expected_revision": 0,
    }
    with capture_turn() as first:
        response = await client.post("/analysis/query", json=payload)
    calls_before_replay = len(adapter.inputs)
    with capture_turn() as replay_capture:
        replay = await client.post("/analysis/query", json=payload)
    return {
        "artifact_version": "analyst-payload-http-v1",
        "request": payload,
        "status": response.status_code,
        "response": response.json(),
        "capture": first,
        "replay_status": replay.status_code,
        "replay": replay.json(),
        "replay_capture": replay_capture,
        "model_inputs": adapter.inputs,
        "calls_before_replay": calls_before_replay,
        "calls_after_replay": len(adapter.inputs),
        "budget_before": "0.125",
        "budget_after": (await redis.get(key)).decode(),
        "real_provider_requests": 0,
    }


def save_receipt(tmp_path, record_property, name, receipt):
    directory = Path(os.environ.get("KNICKSIQ_PAYLOAD_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{name}.json"
    with destination.open("x") as file:
        json.dump(receipt, file, indent=2)
    record_property("payload_artifact", str(destination))


def assert_committed_replay(receipt):
    assert receipt["status"] == receipt["replay_status"] == 200
    assert receipt["response"]["state_committed"]
    assert receipt["response"] == receipt["replay"]
    assert receipt["calls_before_replay"] == receipt["calls_after_replay"]
    assert receipt["replay_capture"] == {
        "searches": [],
        "tools": [],
        "turn": {"replayed": True, "model_calls": 0},
    }
    assert receipt["budget_before"] == receipt["budget_after"]


class SyntheticAdapter:
    """Protocol-only responses: exact backend values, with a real review round."""

    last_metadata = {"usage": {"cost": 0}, "provider": "synthetic-payload-regression"}

    def __init__(self, tool):
        self.tool = tool
        self.inputs = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        self.inputs.append(
            {"system": system, "user": payload, "input_bytes": len((system + user).encode())}
        )
        if payload["schema"]["title"] == "AnswerReview":
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": span,
                            "assertion_type": "factual",
                            "verdict": "supported",
                            "offending_text": None,
                            "supporting_claim_ids": [c["claim_id"] for c in payload["claims"]],
                            "supporting_evidence_ids": [],
                            "reason": "Exact backend statement in a synthetic protocol test.",
                        }
                        for span in payload["review_spans"]
                    ],
                    "follow_up_reviews": [],
                }
            )
        if not payload["claims"]:
            return json.dumps({"action": "call_tools", "tools": [self.tool], "answer": None})
        answer = {
            "text": " ".join(c["statement"] for c in payload["claims"]),
            "claims": [
                {"claim_id": c["claim_id"], "displayed_value": c["value"]}
                for c in payload["claims"]
            ],
            "evidence_ids": [],
            "fact_ids": [],
            "follow_up_questions": [],
        }
        if payload["schema"]["title"] == "ProposedAnswer":
            return json.dumps(answer)
        return json.dumps(
            {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
        )


async def test_current_discovery_survives_oversized_result_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    question = "What did Jalen Brunson average against Boston?"
    adapter = SyntheticAdapter(
        {"name": "get_player_stats", "question": question, "metric": "points"}
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    execute = AnalystTools.execute
    seam = {}

    async def result_with_oversized_record(self, call):
        result = await execute(self, call)
        if call.name != "get_player_stats":
            return result
        # Real SQL discovery is left intact. Reproduce a whole oversized source
        # and a duplicate result/discovery identity at the tool boundary.
        assert self.discovery and len(self.discovery.evidence) >= 2
        priority = self.discovery.evidence[-1]
        oversized = priority.model_copy(
            update={"evidence_id": "synthetic:oversized-current-result", "text": "x" * 9000}
        )
        unrelated = Evidence(
            evidence_id="synthetic:unrelated-prior-game",
            release_id=self.release.version,
            game_id=999999,
            text="Unrelated source hydrated from an earlier turn.",
        )
        self.evidence[oversized.evidence_id] = oversized
        self.evidence[unrelated.evidence_id] = unrelated
        seam.update(
            discovery=[e.model_dump(mode="json") for e in self.discovery.evidence],
            priority_id=priority.evidence_id,
            oversized=oversized.model_dump(mode="json"),
            unrelated=unrelated.model_dump(mode="json"),
            claims=[c.model_dump(mode="json") for c in result.claims],
        )
        return result.model_copy(update={"evidence": [oversized, priority, priority]})

    monkeypatch.setattr(AnalystTools, "execute", result_with_oversized_record)
    receipt = await exchange(client, local_redis, adapter, "source-union", question)
    receipt["controlled_tool_result"] = seam
    save_receipt(tmp_path, record_property, "source-union", receipt)
    assert_committed_replay(receipt)
    assert receipt["response"]["llm_validated"]
    assert any(s["purpose"] == "canonical_discovery" for s in receipt["capture"]["searches"])
    action_inputs = [p for p in adapter.inputs if p["user"]["schema"]["title"] == "Action"]
    assert len(action_inputs) == 2
    packed = action_inputs[1]["user"]
    ids = [e["evidence_id"] for e in packed["evidence"]]
    expected_order = [seam["priority_id"]] + [
        e["evidence_id"] for e in seam["discovery"] if e["evidence_id"] != seam["priority_id"]
    ]
    assert ids[0] == seam["priority_id"]
    assert len(ids) == len(set(ids))
    assert seam["oversized"]["evidence_id"] not in ids
    assert seam["unrelated"]["evidence_id"] not in ids
    assert len(ids) >= 2, (
        "A nonempty oversized result must not suppress compact canonical discovery"
    )
    assert ids == [identity for identity in expected_order if identity in ids]
    originals = {e["evidence_id"]: e for e in seam["discovery"]}
    assert all(e == originals[e["evidence_id"]] for e in packed["evidence"])
    assert packed["claims"] == seam["claims"]
    for request in adapter.inputs:
        assert request["input_bytes"] <= settings.analyst_input_tokens
        payload = request["user"]
        retained_size = sum(encoded_size([c]) for c in payload["claims"]) + sum(
            encoded_size(e) for e in payload["evidence"]
        )
        assert retained_size <= settings.analyst_evidence_tokens


async def test_oversized_boston_narrative_falls_back_before_dispatch_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    question = "What was the key sequence in the Boston loss?"
    adapter = SyntheticAdapter({"name": "search_archive", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, "oversized-boston", question)
    receipt["bundle"] = {"path": str(BUNDLE), "sha256": SHA}
    save_receipt(tmp_path, record_property, "oversized-boston", receipt)
    assert_committed_replay(receipt)
    body = receipt["response"]
    assert not body["llm_validated"]
    claim = next(
        c["metadata"]["claim"]
        for c in body["citations"]
        if c["type"] == "verified_claim"
        and c["metadata"]["claim"]["metric_id"] == "canonical_game_narrative"
    )
    assert claim["value"]["games"][0]["nba_game_id"] == "0022500320"
    runs = claim["value"]["runs"]
    assert [(r["points"], r["start_sequence"], r["end_sequence"]) for r in runs] == [
        (12, 128, 146),
        (12, 282, 299),
    ]
    assert [[e["sequence"] for e in r["scoring_events"]] for r in runs] == [
        [128, 131, 137, 140, 144, 146],
        [282, 290, 293, 295, 299],
    ]
    assert "2025-12-02" in body["answer"]
    assert all(
        r["start_clock"] in body["answer"] and r["end_clock"] in body["answer"] for r in runs
    )
    assert receipt["calls_before_replay"] == receipt["capture"]["turn"]["model_calls"] == 0, (
        "A required narrative that cannot fit must fall back before provider dispatch"
    )
