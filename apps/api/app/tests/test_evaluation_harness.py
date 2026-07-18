from app.evaluation.harness import EvaluationCase, QueryObservation, evaluate


def _case(**overrides):
    value = {
        "id": "narrative-001",
        "category": "single_game_narrative",
        "question": "How did the Knicks lose the lead?",
        "expected_route": "retrieval_rag",
        "relevant_evidence_ids": ["possession:p2"],
        "required_facts": ["12-2 run", "fourth quarter"],
        "answerable": True,
        "filters": {"opponent": "BOS", "game_id": "g1"},
    }
    value.update(overrides)
    return EvaluationCase.from_dict(value)


def test_report_separates_rerankable_cases_from_retrieval_misses():
    rerankable = QueryObservation(
        _case(),
        {
            "route": "retrieval_rag",
            "answer": "A 12-2 run in the fourth quarter flipped it.",
            "citations": [{"metadata": {"possession_id": "p2"}}],
            "tool_calls": [
                {
                    "tool": "rrf",
                    "candidate_evidence_ids": ["possession:p1", "possession:p2"],
                },
                {"tool": "retrieval_result", "returned_evidence_ids": ["possession:p1"]},
                {"tool": "llm_generate", "cost_usd": 0.01},
            ],
        },
        100,
    )
    missed = QueryObservation(
        _case(id="narrative-002", relevant_evidence_ids=["possession:missing"]),
        {
            "route": "retrieval_rag",
            "answer": "I could not find it.",
            "citations": [],
            "tool_calls": [
                {"tool": "rrf", "candidate_evidence_ids": ["possession:p1"]},
                {"tool": "retrieval_result", "returned_evidence_ids": ["possession:p1"]},
            ],
        },
        300,
    )

    report = evaluate([rerankable, missed])

    assert report.reranker_diagnosis == {
        "reranking_may_help": 1,
        "retrieval_miss": 1,
        "already_top5": 0,
    }
    assert report.metrics["relevant_evidence_recall_at_5"] == 0
    assert report.metrics["relevant_evidence_recall_at_20"] == 0.5
    assert report.metrics["latency_p50_ms"] == 200
    assert report.metrics["llm_calls_per_query"] == 0.5
    assert report.metrics["cost_usd_per_query"] == 0.005


def test_unanswerable_case_scores_explicit_refusal():
    observation = QueryObservation(
        _case(
            id="unsupported-001",
            expected_route=None,
            relevant_evidence_ids=[],
            required_facts=[],
            answerable=False,
        ),
        {"route": None, "answer": "I cannot answer live questions.", "refused": True},
        10,
    )
    assert evaluate([observation]).metrics["correct_abstention_rate"] == 1
