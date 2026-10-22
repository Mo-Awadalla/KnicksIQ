"""The evidence an answer actually references, shared by validation, review and delivery."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.evidence_contracts import Evidence, ProposedAnswer, VerifiedClaim


@dataclass(frozen=True)
class AnswerEvidence:
    claims: dict[str, VerifiedClaim]
    evidence: dict[str, Evidence]


def select_answer_evidence(
    answer: ProposedAnswer,
    available_claims: dict[str, VerifiedClaim],
    supplied_evidence: dict[str, Evidence],
    evidence_registry: dict[str, Evidence],
) -> AnswerEvidence:
    claims: dict[str, VerifiedClaim] = {}
    pending = [use.claim_id for use in answer.claims]
    while pending:
        claim_id = pending.pop()
        if claim_id in claims:
            continue
        claim = available_claims.get(claim_id)
        if claim is None:
            raise ValueError("Answer references a claim that was not supplied")
        claims[claim_id] = claim
        pending.extend(claim.baseline_claim_ids)

    # The writer can cite supplied receipts or receipt ids carried by supplied claims.
    # An unrelated receipt merely present in server memory is not model evidence.
    visible_ids = set(supplied_evidence)
    visible_ids.update(
        ref for claim in available_claims.values() for ref in claim.supporting_evidence_ids
    )
    required_ids = set(answer.evidence_ids)
    required_ids.update(ref for claim in claims.values() for ref in claim.supporting_evidence_ids)
    if not required_ids <= visible_ids:
        raise ValueError("Answer references evidence that was not supplied")
    evidence: dict[str, Evidence] = {}
    for ref in sorted(required_ids):
        item = evidence_registry.get(ref)
        if item is None:
            raise ValueError("Answer references unavailable evidence")
        evidence[ref] = item
    return AnswerEvidence(claims=claims, evidence=evidence)


def review_evidence_view(item: Evidence) -> dict:
    """Source-id lists remain server-side. Their calculated statement and sample survive."""
    data = item.model_dump(mode="json")
    data["metadata"] = {
        key: value for key, value in data["metadata"].items() if key != "source_evidence_ids"
    }
    return data
