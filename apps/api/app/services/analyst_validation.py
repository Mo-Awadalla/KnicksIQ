"""Whole-answer validation: structure, the deterministic number gate, then the reviewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.analyst_provider import encoded
from app.services.analyst_review_checks import review_issues
from app.services.evidence_contracts import (
    AnswerReview,
    ProposedAnswer,
    accepted_follow_ups,
    deterministic_claim_ids,
    split_review_spans,
    validate_review,
    validate_structure,
)

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop

# Review logs keep the loop's logger name, which existing log queries and alerts filter on.
logger = logging.getLogger("app.services.analyst_loop")

FACTUAL_REVIEW_TYPES = frozenset({"factual", "interpretation"})


async def validate_answer(
    loop: AnalystLoop, answer: ProposedAnswer, *, timeout_seconds: float | None = None
) -> tuple[bool, str]:
    """Structure, deterministic number gate, then the independent reviewer; fail closed."""
    if not validate_structure(
        answer,
        loop.sent_claims,
        loop.tools.evidence,
        loop.sent_candidates,
        loop.tools.release.version,
    ):
        return False, (
            "Invalid claim value, release, baseline or reference. displayed_value must equal "
            "the claim's `value` field exactly, not the whole claim object."
        )
    spans = split_review_spans(answer.text)
    # A reviewer sees each claim's supporting_evidence_ids, so those backend-issued
    # receipts are legitimate citations even when the payload omitted their details.
    reviewable = dict(loop.sent_evidence)
    for claim in loop.sent_claims.values():
        for ref in claim.supporting_evidence_ids:
            if ref in loop.tools.evidence:
                reviewable.setdefault(ref, loop.tools.evidence[ref])
    issues = review_issues(
        answer,
        spans,
        loop.sent_claims,
        reviewable,
        loop.tools.manifest(),
        loop.tools.question,
    )
    if issues:
        # Mechanical rejection before any stochastic reviewer verdict.
        return False, "Deterministic evidence check failed: " + "; ".join(issues[:3])
    review = await loop.review(answer, timeout_seconds=timeout_seconds)
    if review is None:
        return False, "Reviewer failed or returned malformed output."
    empty, attachable = citation_gaps(loop, review, answer, spans)
    accepted = validate_review(review, answer, loop.sent_claims, reviewable, spans=spans)
    metadata = loop.trace[-1] if loop.trace else {}
    # The API returns this trace, so the next live occurrence carries the provider and
    # the citation shape that the 15/21 run did not record.
    metadata.update(
        {
            "review_spans": len(review.assertions),
            "review_empty_id_spans": len(empty),
            "review_attachable_spans": len(attachable),
            "review_accepted": accepted,
        }
    )
    if attachable:
        # Production measurement of the dropped-citation repair: spans the reviewer
        # supported without ids and the backend could attribute deterministically.
        logger.info(
            "analyst_review_citation_gaps request_id=%s provider=%s accepted=%s "
            "spans=%d empty_id_spans=%d attachable_spans=%d",
            loop.request_id,
            metadata.get("provider"),
            accepted,
            len(review.assertions),
            len(empty),
            len(attachable),
            extra={
                "request_id": loop.request_id,
                "provider": metadata.get("provider"),
                "finish_reason": metadata.get("finish_reason"),
                "accepted": accepted,
                "spans": len(review.assertions),
                "empty_id_spans": len(empty),
                "attachable_spans": len(attachable),
            },
        )
    if not accepted:
        unsupported = sum(1 for item in review.assertions if item.verdict != "supported")
        logger.warning(
            "analyst_review_rejected request_id=%s provider=%s finish_reason=%s "
            "spans=%d empty_id_spans=%d attachable_spans=%d unsupported_spans=%d",
            loop.request_id,
            metadata.get("provider"),
            metadata.get("finish_reason"),
            len(review.assertions),
            len(empty),
            len(attachable),
            unsupported,
            extra={
                "request_id": loop.request_id,
                "provider": metadata.get("provider"),
                "finish_reason": metadata.get("finish_reason"),
                "spans": len(review.assertions),
                "empty_id_spans": len(empty),
                "attachable_spans": len(attachable),
                "unsupported_spans": unsupported,
            },
        )
        return False, encoded(review.model_dump())
    loop.accepted_suggestions = accepted_follow_ups(review, answer, loop.sent_claims, reviewable)
    return True, ""


def citation_gaps(
    loop: AnalystLoop, review: AnswerReview, answer: ProposedAnswer, spans: list[str]
) -> tuple[list[int], list[int]]:
    """Supported factual spans with no ids, and how many the backend could attribute."""
    empty: list[int] = []
    attachable: list[int] = []
    for index, item in enumerate(review.assertions):
        if item.assertion_type not in FACTUAL_REVIEW_TYPES:
            continue
        if item.supporting_claim_ids or item.supporting_evidence_ids:
            continue
        empty.append(index)
        span = spans[index] if index < len(spans) else item.text
        if deterministic_claim_ids(span, answer, loop.sent_claims):
            attachable.append(index)
    return empty, attachable
