"""Model-facing claim views and the budgeted provider payload."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.analyst_provider import compact_schema, encoded, token_upper_bound
from app.services.answer_evidence import review_evidence_view, select_answer_evidence
from app.services.evidence_contracts import (
    INTERPRETATION_POLICY,
    Candidate,
    Evidence,
    ProposedAnswer,
    VerifiedClaim,
    split_review_spans,
)

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop

_SERVER_SIDE_CLAIM_FIELDS = {
    "game_ids",
    "calculation_version",
    "metric_definition_version",
    "release_id",
}


def claim_view(claim: VerifiedClaim) -> dict[str, Any]:
    """The claim as the model sees it.

    Each claim used to carry ~100 game ids plus version strings and null filters. Four sibling
    claims (wins, losses, points, margin) did not fit the input budget together, so the model
    answered "no points total was returned" while the backend had it. Everything omitted is
    server-side provenance that validation reads from the registry, never from the model.
    """
    full = claim.model_dump(mode="json", exclude=_SERVER_SIDE_CLAIM_FIELDS)
    view = {key: value for key, value in full.items() if value not in (None, [], {})}
    view["value"] = full["value"]
    view["filters"] = {k: v for k, v in full["filters"].items() if v not in (None, [], {})}
    return {key: value for key, value in view.items() if key != "filters" or value}


def review_claim_view(claim: VerifiedClaim) -> dict[str, Any]:
    """Keep factual coverage context, but omit the generic eligibility policy."""
    view = claim_view(claim)
    view.pop("eligibility", None)
    return view


def build_payload(
    loop: AnalystLoop,
    schema: type,
    *,
    answer: ProposedAnswer | None = None,
    repair: str | None = None,
    review: bool = False,
    instruction_bytes: int = 1700,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": compact_schema(schema),
        "policy": INTERPRETATION_POLICY,
        "requested_question": loop.tools.question,
        "capabilities": loop.tools.manifest(),
        "claims": [],
        "evidence": [],
        "candidates": [],
    }
    if loop.preplanned and not review:
        payload["preplanned_tools"] = list(loop.preplanned)
    if review:
        if answer is None:
            raise ValueError("Review requires a proposed answer")
        selected = select_answer_evidence(
            answer, loop.sent_claims, loop.sent_evidence, loop.tools.evidence
        )
        payload["proposed_answer"] = answer.model_dump(mode="json")
        payload["review_spans"] = split_review_spans(answer.text)
        payload["follow_up_questions"] = answer.follow_up_questions
        payload["claims"] = [review_claim_view(c) for c in selected.claims.values()]
        payload["evidence"] = [review_evidence_view(e) for e in selected.evidence.values()]
        evidence_size = token_upper_bound(encoded(payload["claims"])) + token_upper_bound(
            encoded(payload["evidence"])
        )
        if evidence_size > loop.settings.analyst_evidence_tokens:
            raise ValueError("Full referenced evidence cannot fit reviewer input")
        if (
            token_upper_bound(encoded(payload)) + instruction_bytes
            > loop.settings.analyst_input_tokens
        ):
            raise ValueError("Required review context exceeds input budget")
        return payload
    else:
        payload.update(
            question=loop.tools.question,
            context=loop.context,
            results=[
                {
                    "status": r.status,
                    "message": r.message,
                    "choices": r.choices,
                    "scope": r.scope,
                }
                for r in loop.results
            ],
            tool_rounds_remaining=loop.settings.analyst_max_tool_rounds - loop.rounds,
        )
        if answer:
            payload["proposed_answer"] = answer.model_dump(mode="json")
            payload["repair"] = repair
        # Newly investigated material takes priority over previous turn claims.
        claims = list({c.claim_id: c for r in loop.results for c in r.claims}.values())
        if not claims:
            claims = list(loop.tools.claims.values())
        evidence = list({e.evidence_id: e for r in loop.results for e in r.evidence}.values())
        if not evidence:
            evidence = list(loop.tools.evidence.values())
        candidates = list(loop.tools.candidates.values())
    limit = loop.settings.analyst_input_tokens - instruction_bytes
    if token_upper_bound(encoded(payload)) > limit:
        raise ValueError("Required review/action context exceeds input budget")

    def retain_claims(
        base: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, VerifiedClaim], dict[str, Candidate], int]:
        retained = base
        kept_claims: dict[str, VerifiedClaim] = {}
        kept_candidates: dict[str, Candidate] = {}
        retained_size = 0
        for claim in claims:
            # Claim + all baseline claims are an indivisible record group. Evidence details
            # can be omitted, since complete IDs remain resolvable in the server registry.
            candidate_refs = {
                ref
                for candidate in candidates
                if claim.claim_id in candidate.claim_ids
                for ref in candidate.claim_ids
            }
            group_ids = {claim.claim_id, *claim.baseline_claim_ids, *candidate_refs}
            group_ids.update(
                ref for cid in list(group_ids) for ref in loop.tools.claims[cid].baseline_claim_ids
            )
            group = [loop.tools.claims[ref] for ref in sorted(group_ids) if ref not in kept_claims]
            data = [claim_view(c) for c in group]
            size = token_upper_bound(encoded(data))
            related = [
                c
                for c in candidates
                if c.fact_id not in kept_candidates
                and set(c.claim_ids) <= (kept_claims.keys() | {g.claim_id for g in group})
            ]
            candidate_payload = {
                **retained,
                "claims": retained["claims"] + data,
                "candidates": retained["candidates"] + [c.model_dump() for c in related],
            }
            if retained_size + size > loop.settings.analyst_evidence_tokens or (
                token_upper_bound(encoded(candidate_payload)) > limit
            ):
                continue
            retained = candidate_payload
            retained_size += size
            kept_claims.update({c.claim_id: c for c in group})
            kept_candidates.update({c.fact_id: c for c in related})
        return retained, kept_claims, kept_candidates, retained_size

    payload, sent_claims, sent_candidates, evidence_size = retain_claims(payload)
    if not sent_claims and claims and "preplanned_tools" in payload:
        # The prefetch hint is an optimization; the claims are the answer. Drop the hint
        # before a few bytes of it can hide every record from the writer.
        without_hint = {key: value for key, value in payload.items() if key != "preplanned_tools"}
        retried = retain_claims(without_hint)
        if retried[1]:
            payload, sent_claims, sent_candidates, evidence_size = retried
    # Prioritize evidence supporting the retained claims.
    sent_evidence: dict[str, Evidence] = {}
    refs = {ref for c in sent_claims.values() for ref in c.supporting_evidence_ids}
    evidence.sort(key=lambda e: e.evidence_id not in refs)
    for item in evidence:
        data = item.model_dump(mode="json")
        size = token_upper_bound(encoded(data))
        candidate_payload = {**payload, "evidence": payload["evidence"] + [data]}
        if evidence_size + size <= loop.settings.analyst_evidence_tokens and (
            token_upper_bound(encoded(candidate_payload)) <= limit
        ):
            payload = candidate_payload
            evidence_size += size
            sent_evidence[item.evidence_id] = item
    loop.sent_claims, loop.sent_evidence = sent_claims, sent_evidence
    loop.sent_candidates = sent_candidates
    return payload
