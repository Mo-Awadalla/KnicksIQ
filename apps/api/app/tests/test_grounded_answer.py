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
