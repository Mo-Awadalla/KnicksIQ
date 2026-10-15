"""Sealed claim values and wording repair through public HTTP, SQL, and Redis."""

import json

import pytest
from app.core.db import AsyncSessionLocal
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    configure,
    exchange,
    save_receipt,
)
from app.tests.test_player_intelligence import _seed_release_stats


class ValueFormatAdapter:
    """Replay the observed prose-value mistake without accepting it locally."""

    last_metadata = {"usage": {"cost": 0}, "provider": "synthetic-value-format-regression"}

    def __init__(self, behavior, question):
        self.behavior = behavior
        self.question = question
        self.inputs = []
        self.outputs = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        self.inputs.append(
            {"system": system, "user": payload, "input_bytes": len((system + user).encode())}
        )
        title = payload["schema"]["title"]
        if title == "AnswerReview":
            response = {
                "assertions": [
                    {
                        "text": span,
                        "assertion_type": "factual",
                        "verdict": "unsupported" if "secret tactic" in span else "supported",
                        "offending_text": span if "secret tactic" in span else None,
                        "supporting_claim_ids": [
                            c["claim_id"] for c in analyst_loop.payload_claims(payload)
                        ],
                        "supporting_evidence_ids": [],
                        "reason": "No claim establishes a secret tactic."
                        if "secret tactic" in span
                        else "Exact backend statement in a synthetic protocol test.",
                    }
                    for span in payload["review_spans"]
                ],
                "follow_up_reviews": [],
            }
        elif not analyst_loop.payload_claims(payload):
            response = {
                "action": "call_tools",
                "tools": [
                    {"name": "get_player_stats", "question": self.question, "metric": "points"}
                ],
                "answer": None,
            }
        else:
            claim = analyst_loop.payload_claims(payload)[0]
            expected = {
                "claim_id": claim["claim_id"],
                "displayed_value": claim["value"],
                "decimal_places": None,
            }
            use = {**expected, "displayed_value": claim["statement"]}
            text = claim["statement"]
            if self.behavior == "unsupported-wording" or (
                self.behavior == "repair" and not self.outputs
            ):
                use = expected
                text += " A secret tactic caused his scoring."
            elif self.behavior == "repair":
                assert payload.get("repair")
                use = expected
            elif self.behavior == "wrong-number":
                use = {**expected, "displayed_value": claim["value"] + 1}
            answer = {
                "text": text,
                "claims": [use],
                "evidence_ids": [],
                "fact_ids": [],
                "follow_up_questions": [],
            }
            response = (
                answer
                if title == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer}
            )
        self.outputs.append(response)
        return json.dumps(analyst_loop.encode_model_response(payload, response))


@pytest.mark.parametrize(
    "behavior", ["repair", "stubborn-prose", "wrong-number", "unsupported-wording"]
)
async def test_value_format_repair_and_rejection_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    behavior,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_object")
    monkeypatch.setattr(settings, "analyst_max_model_calls", 6)
    monkeypatch.setattr(settings, "analyst_deadline_seconds", 30)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    question = "What was Brunson's scoring average over his last 2 appearances?"
    adapter = ValueFormatAdapter(behavior, question)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"value-format-{behavior}", question)
    receipt["scenario"] = behavior
    receipt["synthetic_model_outputs"] = adapter.outputs
    save_receipt(tmp_path, record_property, f"value-format-{behavior}", receipt)
    assert receipt["status"] == receipt["replay_status"] == 200
    assert receipt["response"]["state_committed"]
    assert receipt["response"] == receipt["replay"]
    assert receipt["calls_before_replay"] == receipt["calls_after_replay"]
    assert receipt["replay_capture"] == {
        "searches": [],
        "tools": [],
        "turn": {"replayed": True, "model_calls": 0},
    }
    # Multiple Redis floating-point reservations can leave sub-cent rounding
    # noise. Retain the raw balances and allow only machine precision here.
    assert float(receipt["budget_after"]) == pytest.approx(
        float(receipt["budget_before"]), abs=1e-12, rel=0
    )
    body = receipt["response"]
    assert body["llm_validated"] is (behavior == "repair")
    assert "25" in body["answer"]
    assert "secret tactic" not in body["answer"]
    if behavior == "repair":
        corrected = adapter.outputs[2]["claims"][0]
        assert type(corrected["displayed_value"]) in (int, float)
        assert corrected["displayed_value"] == 25
        assert all(a["verdict"] == "supported" for a in adapter.outputs[3]["assertions"])
    elif behavior == "unsupported-wording":
        assert any(a["verdict"] == "unsupported" for a in adapter.outputs[-1]["assertions"])
    assert receipt["calls_before_replay"] <= settings.analyst_max_model_calls
    for request in adapter.inputs:
        assert request["input_bytes"] <= settings.analyst_input_tokens


@pytest.mark.parametrize("behavior", ["compliant", "oversized-assertion", "oversized-follow-up"])
async def test_review_reason_bounds_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    behavior,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_object")
    monkeypatch.setattr(settings, "analyst_max_model_calls", 6)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    question = "What was Brunson's scoring average over his last 2 appearances?"
    outputs = []

    class BoundedReasonAdapter(SyntheticAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            response = analyst_loop.decode_model_response(
                payload, json.loads(await super().generate(system=system, user=user))
            )
            if payload["schema"]["title"] == "AnswerReview":
                for assertion in response["assertions"]:
                    assertion["reason"] = (
                        "Supported by the complete referenced claim."
                        if behavior != "oversized-assertion"
                        else "x" * 501
                    )
                response["follow_up_reviews"] = [
                    {
                        "text": suggestion,
                        "verdict": "supported",
                        "supporting_claim_ids": [
                            c["claim_id"] for c in analyst_loop.payload_claims(payload)
                        ],
                        "supporting_evidence_ids": [],
                        "reason": "x" * 501
                        if behavior == "oversized-follow-up"
                        else "The same archive supports this follow-up.",
                    }
                    for suggestion in payload["follow_up_questions"]
                ]
            elif analyst_loop.payload_claims(payload):
                answer = (
                    response
                    if payload["schema"]["title"] == "ProposedAnswer"
                    else response["answer"]
                )
                answer["follow_up_questions"] = [
                    "What was Brunson's scoring average in those appearances?"
                ]
            outputs.append(response)
            return json.dumps(analyst_loop.encode_model_response(payload, response))

    adapter = BoundedReasonAdapter(
        {"name": "get_player_stats", "question": question, "metric": "points"}
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, local_redis, adapter, f"review-reason-{behavior}", question)
    receipt["scenario"] = behavior
    receipt["synthetic_model_outputs"] = outputs
    save_receipt(tmp_path, record_property, f"review-reason-{behavior}", receipt)
    assert receipt["status"] == receipt["replay_status"] == 200
    assert receipt["response"]["state_committed"]
    assert receipt["response"] == receipt["replay"]
    assert receipt["calls_before_replay"] == receipt["calls_after_replay"]
    assert receipt["replay_capture"] == {
        "searches": [],
        "tools": [],
        "turn": {"replayed": True, "model_calls": 0},
    }
    assert float(receipt["budget_after"]) == pytest.approx(
        float(receipt["budget_before"]), abs=1e-12, rel=0
    )
    assert receipt["response"]["llm_validated"] is (behavior == "compliant")
    assert "25" in receipt["response"]["answer"]
    if behavior == "compliant":
        assert len(receipt["response"]["follow_up_questions"]) == 1
    else:
        assert receipt["response"]["follow_up_questions"] == []
        key = "assertions" if behavior == "oversized-assertion" else "follow_up_reviews"
        assert len(outputs[-1][key][0]["reason"]) == 501
    for request in adapter.inputs:
        assert request["input_bytes"] <= settings.analyst_input_tokens
