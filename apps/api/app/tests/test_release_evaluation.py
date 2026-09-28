"""Fixed-contract runner failures specified before implementation.

Reject incomplete/unfrozen gold, unresolved targets, altered questions, missing
owner signature, output/contract hash mismatches, missing semantic traces and
ambiguous outcome scoring. Never spend from a disabled run. Reviews require
actual answer spans and evidence, not phrase matching. Keep all fixed cases.
"""

import hashlib
import json
from pathlib import Path

import pytest
from app.evaluation.release_runner import load_contract, score_reviewed, validate_contract
from app.services.release_evidence import fixed_case_ids


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fixture_contract():
    source = Path(__file__).parents[1] / "evaluation/questions.jsonl"
    questions = [json.loads(line) for line in source.read_text().splitlines()]
    return {
        "version": 1,
        "status": "frozen",
        "questions_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scoring_version": "release-review-v1",
        "cases": [
            {
                "id": q["id"],
                "question": q["question"],
                "context": q.get("context", []),
                "semantic_member": q["answerable"] and q.get("expected_route") == "retrieval_rag",
                "semantic_targets": ["canonical:fixture"]
                if q["answerable"] and q.get("expected_route") == "retrieval_rag"
                else [],
                "disposition": "clarify",
                "facts": [],
                "decision_status": "settled",
                "decision_basis": "synthetic test only",
            }
            for q in questions
        ],
    }


def test_all_original_cases_and_semantic_cases_required():
    contract = fixture_contract()
    validate_contract(contract)
    contract["cases"].pop()
    with pytest.raises(ValueError):
        validate_contract(contract)
    contract = fixture_contract()
    next(c for c in contract["cases"] if c["semantic_member"])["semantic_targets"] = []
    with pytest.raises(ValueError):
        validate_contract(contract)
    contract = fixture_contract()
    contract["cases"][0]["question"] = "changed"
    with pytest.raises(ValueError):
        validate_contract(contract)


def test_frozen_labels_still_require_explicit_content_bound_owner_approval(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(fixture_contract()))
    approval = tmp_path / "approval.json"
    approval.write_text("{}")
    with pytest.raises(ValueError):
        load_contract(path, approval)
    approval.write_text(
        json.dumps(
            {
                "owner": "synthetic owner",
                "approved_at": "2026-01-01",
                "expectations_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    assert len(load_contract(path, approval)["cases"]) == 120
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError):
        load_contract(path, approval)


def observations_and_reviews(contract):
    observations = []
    reviews = []
    for case in contract["cases"]:
        observation = {
            "case_id": case["id"],
            "response": {"answer": "Which game?", "citations": []},
            "capture": {
                "searches": [
                    {
                        "returned_evidence_ids": ["runtime:fixture"],
                        "candidate_evidence_ids": ["runtime:fixture"],
                    }
                ]
            },
            "latency_ms": 1,
        }
        observations.append(observation)
        reviews.append(
            {
                "case_id": case["id"],
                "observation_sha256": digest(observation),
                "reviewer": "synthetic reviewer",
                "actual_disposition": "clarify",
                "rationale": "Requests missing game scope.",
                "unsupported_assertions": False,
                "assertions": [
                    {
                        "start": 0,
                        "end": 11,
                        "classification": "clarification",
                        "canonical_fact_ids": [],
                    }
                ],
                "numeric_correct": True,
                "entity_correct": True,
                "citation_correct": True,
                "paraphrase_correct": True,
            }
        )
    return observations, reviews


def test_clarification_is_not_refusal_and_missing_trace_is_not_omitted():
    contract = fixture_contract()
    observations, reviews = observations_and_reviews(contract)
    result = score_reviewed(
        contract, observations, reviews, {"runtime:fixture": "canonical:fixture"}, "primary"
    )
    assert result["metrics"]["query_count"] == 120
    assert result["metrics"]["semantic_case_count"] == 50
    assert result["metrics"]["correct_abstention_rate"] == 1
    reviews[0]["actual_disposition"] = "refuse"
    observations[next(i for i, c in enumerate(contract["cases"]) if c["semantic_member"])][
        "capture"
    ]["searches"] = []
    result = score_reviewed(
        contract, observations, reviews, {"runtime:fixture": "canonical:fixture"}, "primary"
    )
    assert result["metrics"]["correct_abstention_rate"] < 1
    assert result["metrics"]["missing_ranked_traces"] == 1
    assert result["metrics"]["missing_labels"] == 1  # Modified response needs a newly bound review.
    assert result["metrics"]["semantic_case_count"] == 50


def test_missing_reviews_cannot_create_a_passing_subset():
    contract = fixture_contract()
    observations, reviews = observations_and_reviews(contract)
    result = score_reviewed(contract, observations, reviews[:-1], {}, "disabled")
    assert result["metrics"]["missing_labels"] == 1
    assert result["metrics"]["query_count"] == len(fixed_case_ids())


def factual_review_fixture():
    """Complete synthetic review; never a label for the real release corpus."""
    contract = fixture_contract()
    case = contract["cases"][0]
    fact = {"metric": "points", "value": 25, "canonical_evidence_ids": ["canonical:fixture"]}
    case.update(disposition="answer", facts=[fact])
    observations, reviews = observations_and_reviews(contract)
    observations[0]["response"] = {
        "answer": "25 points.",
        "citations": [{"metadata": {"evidence_id": "runtime:fixture"}}],
    }
    reviews[0].update(
        observation_sha256=digest(observations[0]),
        actual_disposition="answer",
        assertions=[
            {
                "start": 0,
                "end": 10,
                "classification": "factual",
                "canonical_fact_ids": [digest(fact)],
                "citation_evidence_ids": ["runtime:fixture"],
            }
        ],
    )
    return contract, observations, reviews


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_fact",
        "unknown_classification",
        "missing_citation",
        "invented_citation",
        "wrong_source",
        "omitted_fact",
    ],
)
def test_factual_review_requires_frozen_fact_and_actual_mapped_receipt(fault):
    # Failure matrix specified before implementation: arbitrary fact names,
    # invented classifications, unreturned citations, wrong mapped sources and
    # incomplete expected facts must never be certified by reviewer booleans.
    contract, observations, reviews = factual_review_fixture()
    mapping = {"runtime:fixture": "canonical:fixture"}
    good = score_reviewed(contract, observations, reviews, mapping, "primary")
    assert good["metrics"]["missing_labels"] == 0
    assert good["metrics"]["citation_correctness"] == 1
    assertion = reviews[0]["assertions"][0]
    if fault == "foreign_fact":
        assertion["canonical_fact_ids"] = ["fabricated-fact"]
    elif fault == "unknown_classification":
        assertion["classification"] = "anything-goes"
    elif fault == "missing_citation":
        assertion["citation_evidence_ids"] = []
    elif fault == "invented_citation":
        assertion["citation_evidence_ids"] = ["never-returned"]
        mapping["never-returned"] = "canonical:fixture"
    elif fault == "wrong_source":
        mapping["runtime:fixture"] = "canonical:unrelated"
    else:
        contract["cases"][0]["facts"].append(
            {"metric": "rebounds", "value": 10, "canonical_evidence_ids": ["canonical:fixture"]}
        )
    scored = score_reviewed(contract, observations, reviews, mapping, "primary")
    assert scored["metrics"]["citation_correctness"] == 0
    assert scored["metrics"]["missing_labels"] == 1
    assert scored["failures"][0]["case_id"] == contract["cases"][0]["id"]


def test_scoring_command_binds_inputs_and_preserves_previous_evidence(tmp_path, monkeypatch):
    # Pipeline failure matrix: score a different contract/run, changed reviews,
    # silently overwrite old metrics, or accept incomplete/failed collection.
    from app.evaluation.release_runner import main

    contract, observations, reviews = factual_review_fixture()
    paths = {
        name: tmp_path / f"{name}.json"
        for name in ("contract", "approval", "observations", "reviews", "mapping", "result")
    }
    paths["contract"].write_text(json.dumps(contract))
    expectation_hash = hashlib.sha256(paths["contract"].read_bytes()).hexdigest()
    paths["approval"].write_text(
        json.dumps(
            {
                "owner": "synthetic",
                "approved_at": "2026-01-01",
                "expectations_sha256": expectation_hash,
            }
        )
    )
    captured = {
        "status": "captured_pending_semantic_review",
        "mode": "primary",
        "expectations_sha256": expectation_hash,
        "approval_sha256": hashlib.sha256(paths["approval"].read_bytes()).hexdigest(),
        "observations": observations,
    }
    paths["observations"].write_text(json.dumps(captured))
    paths["reviews"].write_text(json.dumps(reviews))
    paths["mapping"].write_text(json.dumps({"runtime:fixture": "canonical:fixture"}))
    args = [
        "release_runner",
        str(paths["contract"]),
        "--approval",
        str(paths["approval"]),
        "--mode",
        "primary",
        "--output",
        str(paths["result"]),
        "--observations",
        str(paths["observations"]),
        "--reviews",
        str(paths["reviews"]),
        "--mapping",
        str(paths["mapping"]),
    ]
    monkeypatch.setattr("sys.argv", args)
    main()
    result = json.loads(paths["result"].read_text())
    assert result["metrics"]["missing_labels"] == 0
    for name in ("contract", "approval", "observations", "reviews", "mapping"):
        assert result["inputs"][name] == hashlib.sha256(paths[name].read_bytes()).hexdigest()
    original = paths["result"].read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert paths["result"].read_bytes() == original
    captured["expectations_sha256"] = "wrong"
    paths["observations"].write_text(json.dumps(captured))
    args[args.index("--output") + 1] = str(tmp_path / "mismatched.json")
    with pytest.raises(ValueError, match="binding"):
        main()
    assert not (tmp_path / "mismatched.json").exists()


def test_multi_source_mapping_keeps_aggregate_receipts_and_recall():
    # A calculation may map to several source documents; neither collapse to
    # one source nor treating a list as a hashable ID is a valid scorer behavior.
    contract, observations, reviews = factual_review_fixture()
    result = score_reviewed(
        contract,
        observations,
        reviews,
        {"runtime:fixture": ["canonical:fixture", "canonical:another"]},
        "primary",
    )
    assert result["metrics"]["missing_labels"] == 0
    assert result["metrics"]["citation_correctness"] == 1
    assert result["metrics"]["semantic_recall_at_5"] == 1
