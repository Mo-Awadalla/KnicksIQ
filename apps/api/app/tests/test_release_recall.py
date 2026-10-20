"""Retrieval scoring follows each question's scope; the metric never caps a target list.

Recall@k uses k = max(5, number of targets). A context-free "that game" clarification has no
candidate games, so it is correct only when the analyst asks and retrieves no game.
"""

import pytest
from app.evaluation.release_runner import recall_at_k, score_reviewed, validate_contract
from app.tests.test_release_evaluation import digest, fixture_contract, observations_and_reviews

NINE = [f"canonical:game-{i}" for i in range(9)]
NINE_MAPPING = {f"runtime:game-{i}": f"canonical:game-{i}" for i in range(9)}


def test_recall_at_k_uses_every_target_when_scope_exceeds_five():
    returned = [f"runtime:game-{i}" for i in range(9)]
    assert recall_at_k(NINE, returned, NINE_MAPPING) == 1.0
    assert round(recall_at_k(NINE, returned[:5], NINE_MAPPING), 3) == 0.556


def test_recall_at_k_only_counts_the_top_k_returned():
    games = [f"runtime:game-{i}" for i in range(9)]
    noise = [f"runtime:noise-{i}" for i in range(5)]
    assert round(recall_at_k(NINE, noise[:2] + games, NINE_MAPPING), 3) == 0.778
    assert recall_at_k(NINE[:2], noise + games, NINE_MAPPING) == 0
    assert recall_at_k(NINE[:2], noise[:3] + games, NINE_MAPPING) == 1


def context_free_fixture():
    contract = fixture_contract()
    index = next(i for i, c in enumerate(contract["cases"]) if c["semantic_member"])
    contract["cases"][index].update(semantic_targets=[], context_free_clarification=True)
    observations, reviews = observations_and_reviews(contract)
    return contract, observations, reviews, index


def rebind(observations, reviews, index, **review):
    reviews[index].update(review, observation_sha256=digest(observations[index]))


MAPPING = {"runtime:fixture": "canonical:fixture"}


def test_clarification_recall_uses_the_candidates_listed_in_the_answer():
    contract = fixture_contract()
    index = next(i for i, case in enumerate(contract["cases"]) if case["semantic_member"])
    contract["cases"][index]["semantic_targets"] = NINE
    observations, reviews = observations_and_reviews(contract)
    answer = "Candidate games: " + ", ".join(f"Game {i}" for i in range(9)) + ". Which game?"
    observations[index]["response"]["answer"] = answer
    observations[index]["capture"]["searches"] = []
    reviews[index]["assertions"][0]["end"] = len(answer)
    reviews[index]["listed_candidate_game_ids"] = NINE
    rebind(observations, reviews, index)

    mapping = MAPPING | NINE_MAPPING
    result = score_reviewed(contract, observations, reviews, mapping, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == 1
    assert result["metrics"]["missing_ranked_traces"] == 0

    reviews[index]["listed_candidate_game_ids"] = NINE[:5]
    answer = "Candidate games: " + ", ".join(f"Game {i}" for i in range(5)) + ". Which game?"
    observations[index]["response"]["answer"] = answer
    reviews[index]["assertions"][0]["end"] = len(answer)
    rebind(observations, reviews, index)
    result = score_reviewed(contract, observations, reviews, mapping, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == pytest.approx((49 + 5 / 9) / 50)

    reviews[index]["listed_candidate_game_ids"] = NINE + ["canonical:wrong-game"]
    answer = "Candidate games: " + ", ".join([*(f"Game {i}" for i in range(9)), "Game X"])
    answer += ". Which game?"
    observations[index]["response"]["answer"] = answer
    reviews[index]["assertions"][0]["end"] = len(answer)
    rebind(observations, reviews, index)
    result = score_reviewed(contract, observations, reviews, mapping, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == pytest.approx(49 / 50)


def test_context_free_clarification_rejects_conversation_context():
    contract = fixture_contract()
    case = next(c for c in contract["cases"] if c["id"] == "follow_ups-001")
    case.update(semantic_targets=[], context_free_clarification=True)
    with pytest.raises(ValueError):
        validate_contract(contract)


def test_context_free_clarification_rejects_unreturned_candidate_evidence():
    contract, observations, reviews, index = context_free_fixture()
    observations[index]["capture"]["searches"] = [
        {"returned_evidence_ids": [], "candidate_evidence_ids": ["runtime:fixture"]}
    ]
    rebind(observations, reviews, index)
    result = score_reviewed(contract, observations, reviews, MAPPING, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == pytest.approx(49 / 50)



def test_context_free_clarification_scores_only_when_asked_without_game_evidence():
    contract, observations, reviews, index = context_free_fixture()
    validate_contract(contract)
    observations[index]["capture"]["searches"] = []
    rebind(observations, reviews, index)
    result = score_reviewed(contract, observations, reviews, MAPPING, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == 1
    assert result["metrics"]["missing_ranked_traces"] == 0

    contract, observations, reviews, index = context_free_fixture()
    result = score_reviewed(contract, observations, reviews, MAPPING, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == pytest.approx(49 / 50)

    contract, observations, reviews, index = context_free_fixture()
    observations[index]["capture"]["searches"] = []
    rebind(observations, reviews, index, actual_disposition="answer")
    result = score_reviewed(contract, observations, reviews, MAPPING, "primary")
    assert result["metrics"]["semantic_recall_at_5"] == pytest.approx(49 / 50)


def test_empty_semantic_targets_require_an_explicit_context_free_clarification():
    contract, _, _, index = context_free_fixture()
    del contract["cases"][index]["context_free_clarification"]
    with pytest.raises(ValueError):
        validate_contract(contract)
    contract, _, _, index = context_free_fixture()
    contract["cases"][index].update(disposition="answer", facts=[{"metric": "points"}])
    with pytest.raises(ValueError):
        validate_contract(contract)
    contract, _, _, index = context_free_fixture()
    contract["cases"][index]["semantic_targets"] = ["canonical:fixture"]
    with pytest.raises(ValueError):
        validate_contract(contract)
