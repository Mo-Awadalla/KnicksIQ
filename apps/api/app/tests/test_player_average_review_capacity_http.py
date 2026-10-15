"""Replay the fresh 016 writer shape through real socket HTTP/SQL/Redis."""

import json
import os

import pytest
from app.core.db import AsyncSessionLocal
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    encoded_size,
    save_receipt,
)
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from app.tests.test_record_availability_http import record_exchange
from jsonschema import Draft202012Validator


class AverageWithCoverageAndSuggestions(SyntheticAdapter):
    response_schema: dict | None = None

    def __init__(self, verdict):
        super().__init__({})
        self.verdict = verdict

    async def generate(self, *, system, user):
        payload = json.loads(user)
        claims = analyst_loop.payload_claims(payload)
        schema = self.response_schema
        assert schema is not None
        self.inputs.append(
            {
                "system": system,
                "user": payload,
                "schema": schema,
                "input_bytes": len((system + user).encode()) + encoded_size(schema),
            }
        )
        claim = next(c for c in claims if c["metric_id"] == "rebounds:average")
        if payload["schema"]["title"] == "AnswerReview":
            value = {
                "assertions": [
                    {
                        "text": span,
                        "assertion_type": "factual" if index == 0 else "coverage",
                        "verdict": self.verdict,
                        "offending_text": None if self.verdict == "supported" else span,
                        "supporting_claim_ids": [claim["claim_id"]],
                        "supporting_evidence_ids": [],
                        "reason": "Scripted independent review capacity regression.",
                    }
                    for index, span in enumerate(payload["review_spans"])
                ],
                "follow_up_reviews": [
                    {
                        "text": text,
                        "verdict": "supported",
                        "supporting_claim_ids": [claim["claim_id"]],
                        "supporting_evidence_ids": [],
                        "reason": "Uses this player's observed rebound population.",
                    }
                    for text in payload["follow_up_questions"]
                ],
            }
        else:
            name = "Karl-Anthony Towns"
            window = claim["window"]
            missing = next(
                (
                    item
                    for item in claim["coverage_limitations"]
                    if item.startswith("Missing player rows")
                ),
                "",
            )
            caveat = (
                "This covers only observed appearances in the available archive; "
                + (missing.rstrip(".").lower() + " mean " if missing else "")
                + "the archive is not necessarily the complete season."
            )
            text = (
                f"{name} averaged {claim['value']:.1f} rebounds per appearance across "
                f"{claim['sample_size']} observed appearances in the 2025-26 all-phase "
                f"Knicks archive ({window['date_start']} through {window['date_end']}). " + caveat
            )
            value = {
                "text": text,
                "claims": [{"claim_id": claim["claim_id"], "displayed_value": claim["value"]}],
                "evidence_ids": [claim["supporting_evidence_ids"][0]],
                "fact_ids": [],
                "follow_up_questions": [
                    f"How many total rebounds did {name} record across those "
                    f"{claim['sample_size']} appearances?",
                    "What was his highest single-game rebound total in the archive?",
                ],
            }
        wire = analyst_loop.encode_model_response(payload, value)
        Draft202012Validator(schema).validate(wire)
        return json.dumps(wire)


@pytest.mark.parametrize("verdict", ["supported", "unsupported"])
async def test_average_with_coverage_and_suggestions_reaches_review_socket_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    verdict,
):
    settings = configure(monkeypatch)
    monkeypatch.setattr(settings, "analyst_provider_format", "json_schema")
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = AverageWithCoverageAndSuggestions(verdict)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    attempts = []
    original_model = analyst_loop.AnalystLoop.model

    async def recorded_model(loop, schema, **kwargs):
        try:
            return await original_model(loop, schema, **kwargs)
        except (ValueError, RuntimeError, TimeoutError) as exc:
            attempts.append(
                {
                    "schema": schema.__name__,
                    "reason": str(exc),
                    "calls_sent": loop.calls,
                    "remaining_seconds": loop.remaining(),
                }
            )
            raise

    monkeypatch.setattr(analyst_loop.AnalystLoop, "model", recorded_model)
    name = f"average-review-capacity-{verdict}"
    receipt = await record_exchange(
        client,
        local_redis,
        adapter,
        "What was Karl-Anthony Towns' rebounding average?",
        name,
    )
    receipt["model_attempt_errors"] = attempts
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    reviews = [i for i in adapter.inputs if i["user"]["schema"]["title"] == "AnswerReview"]
    assert reviews, "The complete player average must reach independent review."
    assert all(i["input_bytes"] <= 8000 for i in adapter.inputs)
    assert settings.analyst_input_tokens == 8000
    assert settings.analyst_evidence_tokens == 6000
    assert all(len(i["user"]["follow_up_questions"]) == 2 for i in reviews)
    assert all(len(i["user"]["review_spans"]) >= 2 for i in reviews)
    for item in reviews:
        claim = analyst_loop.payload_claims(item["user"])[0]
        expected_sample = 94 if os.environ.get("KNICKSIQ_APPROVED_BUNDLE") else 101
        assert claim["sample_size"] == expected_sample
        source = next(
            evidence
            for evidence in analyst_loop.payload_evidence(item["user"])
            if evidence["evidence_id"] == claim["supporting_evidence_ids"][0]
        )
        expected_refs = {
            f"{claim['release_id']}:game:{game_id}:{claim['subject_id']}"
            for game_id in claim["game_ids"]
        }
        assert len(source["metadata"]["source_evidence_ids"]) == expected_sample
        assert set(source["metadata"]["source_evidence_ids"]) == expected_refs
        assert source["text"] == claim["statement"]
        assert source["metadata"]["denominator"] == claim["denominator"] == expected_sample
    assert receipt["response"]["llm_validated"] is (verdict == "supported")
    assert receipt["real_provider_requests"] == 0
