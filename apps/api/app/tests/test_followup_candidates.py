"""Optional candidate suggestions must not invalidate a grounded main answer."""

from app.services.evidence_contracts import (
    AnswerReview,
    AssertionReview,
    Evidence,
    FollowUpReview,
    ProposedAnswer,
    accepted_follow_ups,
    validate_review,
)


def test_rejected_optional_candidate_preserves_the_answer_and_two_supported_choices():
    questions = [
        "Will the Knicks win tomorrow?",
        "What was the Knicks record?",
        "What was the final margin?",
    ]
    receipt = Evidence(
        evidence_id="game-receipt", release_id="release", text="New York won 119-111."
    )
    answer = ProposedAnswer(
        text="New York won 119-111.",
        evidence_ids=[receipt.evidence_id],
        follow_up_questions=questions,
    )
    review = AnswerReview(
        assertions=[
            AssertionReview(
                text=answer.text,
                assertion_type="factual",
                verdict="supported",
                offending_text=None,
                supporting_claim_ids=[],
                supporting_evidence_ids=[receipt.evidence_id],
                reason="The archived receipt states the score.",
            )
        ],
        follow_up_reviews=[
            FollowUpReview(text=questions[0], verdict="unsupported", reason="Future prediction."),
            FollowUpReview(
                text=questions[1],
                verdict="supported",
                supporting_evidence_ids=[receipt.evidence_id],
                reason="Archived result.",
            ),
            FollowUpReview(
                text=questions[2],
                verdict="supported",
                supporting_evidence_ids=[receipt.evidence_id],
                reason="Archived score.",
            ),
        ],
    )
    evidence = {receipt.evidence_id: receipt}
    assert validate_review(review, answer, {}, evidence) is True
    assert accepted_follow_ups(review, answer, {}, evidence) == questions[1:]
