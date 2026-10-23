"""Whole-answer validation: structure, the deterministic number gate, then the reviewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.analyst_native import required_claim_groups
from app.services.analyst_provider import encoded
from app.services.analyst_review_checks import review_issues
from app.services.answer_evidence import select_answer_evidence
from app.services.evidence_contracts import (
    AnswerReview,
    ProposedAnswer,
    accepted_follow_ups,
    deterministic_claim_ids,
    split_review_spans,
    validate_review,
    validate_structure,
)
from app.services.population_facts import (
    is_player_leader_request,
    is_single_game_high_request,
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
    declared = [
        loop.tools.claims[u.claim_id] for u in answer.claims if u.claim_id in loop.tools.claims
    ]
    requirements = required_claim_groups(loop)
    declared_ids = {claim.claim_id for claim in declared}
    record = requirements.get("record", [])
    if any(not domain & declared_ids for domain in record):
        return False, "Every requested record needs both canonical wins and losses claims."
    if any(not domain & declared_ids for domain in requirements.get("statistics", [])):
        return False, "Every available requested statistical population must be answered."
    scope = loop.tools.scope
    if "profile" in requirements:
        groups = requirements["profile"]
        if not groups or any(not domain & declared_ids for domain in groups):
            return False, "Every requested player profile fact must be answered."
    if scope is not None and not scope.player_ids:
        if "team" in requirements:
            groups = requirements["team"]
            if not groups or any(not domain & declared_ids for domain in groups):
                return False, "Every requested team comparison population must be answered."
        elif is_player_leader_request(loop.tools.question):
            games = loop.tools.selected_games(scope)
            if scope.relative_game_count:
                games = (
                    games[: scope.relative_game_count]
                    if scope.relative_game_order == "first"
                    else games[-scope.relative_game_count :]
                )
            leader_metric_id = (
                f"{scope.metric}:single_game_high"
                if is_single_game_high_request(loop.tools.question)
                else f"{scope.metric}:leaders"
            )
            if not any(
                claim.subject_id == "team:NYK"
                and claim.metric_id == leader_metric_id
                and set(claim.game_ids or []) == {game.id for game in games}
                for claim in declared
            ):
                return False, (
                    "A team leader or single-game high requires the complete requested "
                    "game population."
                )
    if "extreme" in requirements:
        groups = requirements["extreme"]
        if any(not domain & declared_ids for domain in groups) or len(declared) != len(groups):
            return (
                False,
                "Every selected or tied game needs its complete game_score object "
                "and every requested metric.",
            )
    elif loop.tools.narrative:
        from app.services.canonical_narrative import complete_narrative_text

        if not complete_narrative_text(answer.text, declared):
            return False, "Every selected game and tied run must appear in the narrative."
    spans = split_review_spans(answer.text)
    try:
        selected = select_answer_evidence(
            answer, loop.sent_claims, loop.sent_evidence, loop.tools.evidence
        )
    except ValueError as exc:
        return False, str(exc)
    issues = review_issues(
        answer,
        spans,
        selected.claims,
        selected.evidence,
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
    accepted = validate_review(review, answer, selected.claims, selected.evidence, spans=spans)
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
    loop.accepted_suggestions = accepted_follow_ups(
        review, answer, selected.claims, selected.evidence
    )
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
