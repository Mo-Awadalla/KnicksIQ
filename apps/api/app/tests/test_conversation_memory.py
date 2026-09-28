"""Transcript bounds and independently reviewed follow-up suggestions."""

import json

from app.services.conversation_memory import HISTORY_BYTES, bounded_history
from app.services.evidence_contracts import (
    AnswerReview,
    AssertionReview,
    Evidence,
    FollowUpReview,
    ProposedAnswer,
    accepted_follow_ups,
    validate_review,
)


def test_ten_previous_messages_keep_order_and_all_excerpts():
    assert bounded_history([]) == []
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{i}:" + "é" * 2000}
        for i in range(11)
    ]
    retained = bounded_history(messages)
    assert len(retained) == 10
    assert [item["content"].split(":")[0] for item in retained] == [str(i) for i in range(1, 11)]
    assert all(item["content"].startswith(f"{i}:") for i, item in enumerate(retained, 1))
    serialized = json.dumps(retained, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized.encode()) <= HISTORY_BYTES
    assert len(retained[-1]["content"]) > len(retained[0]["content"])


def test_follow_up_rejection_does_not_reject_valid_answer():
    answer = ProposedAnswer(
        text="Ask about a game.",
        follow_up_questions=["What happened in that game?", "Was he injured today?"],
    )
    review = AnswerReview(
        assertions=[
            AssertionReview(
                text=answer.text,
                assertion_type="conversational",
                verdict="supported",
                offending_text=None,
                supporting_claim_ids=[],
                supporting_evidence_ids=[],
                reason="Supported conversational response.",
            )
        ],
        follow_up_reviews=[
            FollowUpReview(
                text=answer.follow_up_questions[0],
                verdict="supported",
                supporting_evidence_ids=["game:1"],
                reason="Archive game is available.",
            ),
            FollowUpReview(
                text=answer.follow_up_questions[1],
                verdict="unsupported",
                reason="Live injury status is unavailable.",
            ),
        ],
    )
    assert validate_review(review, answer, {}, {})
    evidence = {"game:1": Evidence(evidence_id="game:1", release_id="test", text="Game")}
    assert accepted_follow_ups(review, answer, {}, evidence) == ["What happened in that game?"]
    assert (
        accepted_follow_ups(
            review.model_copy(update={"follow_up_reviews": review.follow_up_reviews[:1]}),
            answer,
            {},
            evidence,
        )
        == []
    )
    duplicate_answer = answer.model_copy(
        update={"follow_up_questions": [answer.follow_up_questions[0]] * 2}
    )
    duplicate_review = review.model_copy(
        update={"follow_up_reviews": [review.follow_up_reviews[0]] * 2}
    )
    assert accepted_follow_ups(duplicate_review, duplicate_answer, {}, evidence) == [
        "What happened in that game?"
    ]
