"""Grounding contract for LLM-authored analyst answers."""

from __future__ import annotations

from app.services.grounded_answer import GroundedAnswer, validate_grounded_answer


def test_grounded_answer_rejects_number_missing_from_cited_evidence():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "text": "The Knicks won by 14 points.",
                    "evidence_ids": ["game:1"],
                }
            ]
        }
    )

    assert (
        validate_grounded_answer(
            candidate,
            evidence={"game:1": "The Knicks beat Toronto 110-105."},
        )
        is False
    )


def test_grounded_answer_rejects_entity_missing_from_cited_evidence():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "text": "Jalen Brunson controlled the game.",
                    "evidence_ids": ["game:1"],
                }
            ]
        }
    )

    assert (
        validate_grounded_answer(
            candidate,
            evidence={"game:1": "Toronto controlled the archived game."},
        )
        is False
    )


def test_grounded_answer_rejects_entity_and_number_joined_across_unrelated_evidence():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "text": "Jalen Brunson scored 40 points.",
                    "evidence_ids": ["player:brunson", "player:hart"],
                }
            ]
        }
    )

    assert (
        validate_grounded_answer(
            candidate,
            evidence={
                "player:brunson": "Jalen Brunson played in the game.",
                "player:hart": "Josh Hart scored 40 points.",
            },
        )
        is False
    )


def test_typed_stat_claim_rejects_correct_tokens_with_wrong_relationship():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "claim_type": "player_stat",
                    "text": "Jalen Brunson scored 40 points.",
                    "subject_id": 11,
                    "metric": "points",
                    "value": 40,
                    "game_ids": [7],
                    "evidence_ids": ["fact:box"],
                }
            ]
        }
    )

    assert (
        validate_grounded_answer(
            candidate,
            evidence={"fact:box": "Jalen Brunson and Josh Hart played; 40 points were scored."},
            structured_evidence={
                "fact:box": {
                    "game_id": 7,
                    "players": [
                        {"player_id": 11, "metric": "points", "value": 25},
                        {"player_id": 12, "metric": "points", "value": 40},
                    ],
                }
            },
        )
        is False
    )


def test_typed_stat_claim_accepts_matching_subject_metric_value_and_game():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "claim_type": "player_stat",
                    "text": "Jalen Brunson scored 40 points.",
                    "subject_id": 11,
                    "metric": "points",
                    "value": 40,
                    "game_ids": [7],
                    "evidence_ids": ["fact:box"],
                }
            ]
        }
    )

    assert validate_grounded_answer(
        candidate,
        evidence={"fact:box": "Jalen Brunson scored 40 points in game 7."},
        structured_evidence={
            "fact:box": {
                "game_id": 7,
                "player_id": 11,
                "metric": "points",
                "value": 40,
            }
        },
    )


def test_causal_language_requires_reviewed_or_connected_evidence():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "claim_type": "causal",
                    "text": "The turnover caused the Knicks run.",
                    "evidence_ids": ["sequence:1"],
                }
            ]
        }
    )
    evidence = {"sequence:1": "The turnover caused the Knicks run."}

    assert validate_grounded_answer(candidate, evidence=evidence) is False
    assert validate_grounded_answer(
        candidate,
        evidence=evidence,
        evidence_metadata={"sequence:1": {"connected_sequence": True}},
    )


def test_each_factual_sentence_must_be_supported():
    candidate = GroundedAnswer.model_validate(
        {
            "claims": [
                {
                    "text": ("Jalen Brunson scored 30 points. Josh Hart grabbed 20 rebounds."),
                    "evidence_ids": ["game:1"],
                }
            ]
        }
    )

    assert (
        validate_grounded_answer(
            candidate,
            evidence={"game:1": "Jalen Brunson scored 30 points."},
        )
        is False
    )
