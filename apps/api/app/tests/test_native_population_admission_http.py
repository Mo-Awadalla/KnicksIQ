"""Native leader and single-game-high admission through the analysis HTTP loop."""

import json

import pytest
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    exchange,
    save_receipt,
)
from app.tests.test_population_facts_http import seed_population_release


class NonresponsiveStatisticAdapter(SyntheticAdapter):
    """Offer a valid nonresponsive row and approve its wording in the real review path."""

    def __init__(self, question, nonresponsive_question):
        super().__init__({"name": "get_team_stats", "question": question})
        self.question = question
        self.nonresponsive_question = nonresponsive_question
        self.writer_inputs = []
        self.reviewed_answers = []

    def record(self, system, user, payload):
        self.inputs.append(
            {
                "system": system,
                "user": payload,
                "input_bytes": len((system + user).encode()),
            }
        )

    async def generate(self, *, system, user):
        payload = json.loads(user)
        schema = payload["schema"]["title"]
        if schema == "Action" and not analyst_loop.payload_claims(payload):
            self.record(system, user, payload)
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "action": "call_tools",
                        "tools": [
                            {
                                "name": "get_player_stats",
                                "question": self.nonresponsive_question,
                                "metric": "rebounds",
                                "aggregation": "total",
                            },
                            {"name": "get_team_stats", "question": self.question},
                        ],
                        "answer": None,
                    },
                )
            )

        if schema == "ProposedAnswer":
            self.record(system, user, payload)
            self.writer_inputs.append(payload)
            claims = analyst_loop.payload_claims(payload)
            nonresponsive = next(
                (
                    claim
                    for claim in claims
                    if claim["metric_id"] == "rebounds:total" and claim["subject_id"] != "team:NYK"
                ),
                None,
            )
            if nonresponsive is None:
                # Once the native population is required, deliberately omit it as a
                # model may do when it tries to answer from an unrelated statistic.
                answer = {
                    "text": "The available rebound statistic does not identify the requested high.",
                    "claims": [],
                    "evidence_ids": [],
                    "fact_ids": [],
                    "follow_up_questions": [],
                }
            else:
                answer = {
                    "text": nonresponsive["statement"],
                    "claims": [
                        {
                            "claim_id": nonresponsive["claim_id"],
                            "displayed_value": nonresponsive["value"],
                            "decimal_places": None,
                        }
                    ],
                    "evidence_ids": [],
                    "fact_ids": [],
                    "follow_up_questions": [],
                }
            return json.dumps(analyst_loop.encode_model_response(payload, answer))

        if schema == "AnswerReview":
            self.record(system, user, payload)
            answer = analyst_loop.payload_proposed_answer(payload)
            assert answer is not None
            claim_ids = [claim["claim_id"] for claim in answer["claims"]]
            self.reviewed_answers.append(answer)
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "assertions": [
                            {
                                "text": span,
                                "assertion_type": "factual",
                                "verdict": "supported",
                                "offending_text": None,
                                "supporting_claim_ids": claim_ids,
                                "supporting_evidence_ids": [],
                                "reason": "The selected statement matches its archived statistic.",
                            }
                            for span in payload["review_spans"]
                        ],
                        "follow_up_reviews": [],
                    },
                )
            )

        return await super().generate(system=system, user=user)


@pytest.mark.parametrize(
    ("name", "question", "nonresponsive_question", "expected_metric", "expected_value"),
    [
        (
            "rebound-single-game-high-ties",
            "What was the most rebounds a Knick had in a single game this season?",
            "How many rebounds did Karl-Anthony Towns have this season?",
            "rebounds:single_game_high",
            {
                "maximum": 22,
                "rows": [
                    {
                        "player": "Karl-Anthony Towns",
                        "date": "2026-01-28",
                        "opponent": "TOR",
                        "value": 22,
                    },
                    {
                        "player": "OG Anunoby",
                        "date": "2026-03-13",
                        "opponent": "IND",
                        "value": 22,
                    },
                ],
            },
        ),
        (
            "miami-date-rebound-leader",
            "Who had the most rebounds for New York against Miami on December 21?",
            "How many rebounds did Jalen Brunson have against Miami on December 21?",
            "rebounds:leaders",
            {"leaders": ["Josh Hart"], "total": 10},
        ),
    ],
)
async def test_native_high_or_leader_cannot_be_replaced_by_valid_rebound_total_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
    name,
    question,
    nonresponsive_question,
    expected_metric,
    expected_value,
):
    await seed_population_release()
    configure(monkeypatch)
    adapter = NonresponsiveStatisticAdapter(question, nonresponsive_question)
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)

    receipt = await exchange(client, local_redis, adapter, name, question)
    receipt["adversarial_protocol"] = {
        "writer_required_claim_indexes": [
            payload.get("required_claim_indexes") for payload in adapter.writer_inputs
        ],
        "reviewed_answers": adapter.reviewed_answers,
    }
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)

    tool_results = [tool["result"] for tool in receipt["capture"]["tools"]]
    native_claim = next(
        claim
        for result in tool_results
        for claim in result["claims"]
        if claim["metric_id"] == expected_metric
    )
    assert native_claim["value"] == expected_value
    assert not adapter.reviewed_answers or all(
        use["claim_id"] != native_claim["claim_id"]
        for answer in adapter.reviewed_answers
        for use in answer["claims"]
    )

    assert receipt["response"]["llm_validated"] is False
    response_claim = next(
        claim["metadata"]["claim"]
        for claim in receipt["response"]["citations"]
        if claim["type"] == "verified_claim"
        and claim["metadata"]["claim"]["metric_id"] == expected_metric
    )
    assert response_claim["value"] == expected_value

    answer = receipt["response"]["answer"]
    if expected_metric.endswith("single_game_high"):
        for player, game_date in (
            ("Karl-Anthony Towns", "2026-01-28"),
            ("OG Anunoby", "2026-03-13"),
        ):
            assert player in answer
            assert game_date in answer
        assert "22" in answer
    else:
        assert "Josh Hart" in answer
        assert "10" in answer


async def test_single_game_rebound_high_passes_full_population_review_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    configure(monkeypatch)
    question = "What was the most rebounds a Knick had in a single game this season?"
    adapter = SyntheticAdapter(
        {
            "name": "get_team_stats",
            "question": question,
            "metric": "leaders",
            "aggregation": "total",
        }
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)

    receipt = await exchange(
        client,
        local_redis,
        adapter,
        "single-game-rebound-high-positive",
        question,
    )
    save_receipt(tmp_path, record_property, "single-game-rebound-high-positive", receipt)
    assert_committed_replay(receipt)

    response = receipt["response"]
    assert response["llm_validated"] is True
    claim = next(
        citation["metadata"]["claim"]
        for citation in response["citations"]
        if citation["type"] == "verified_claim"
        and citation["metadata"]["claim"]["metric_id"] == "rebounds:single_game_high"
    )
    assert claim["value"] == {
        "maximum": 22,
        "rows": [
            {
                "player": "Karl-Anthony Towns",
                "date": "2026-01-28",
                "opponent": "TOR",
                "value": 22,
            },
            {
                "player": "OG Anunoby",
                "date": "2026-03-13",
                "opponent": "IND",
                "value": 22,
            },
        ],
    }
    assert "Karl-Anthony Towns" in response["answer"]
    assert "OG Anunoby" in response["answer"]
    assert "2026-01-28" in response["answer"]
    assert "2026-03-13" in response["answer"]
