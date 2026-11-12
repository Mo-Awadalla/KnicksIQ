"""Committed response shaping from verified backend facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.analyst_citations import CITATION_TITLES, collection
from app.services.evidence_contracts import Evidence, ProposedAnswer, ToolResult, VerifiedClaim

if TYPE_CHECKING:
    from app.services.query_resolution import ResolvedQuery


def citations(
    claims: list[VerifiedClaim], answer: ProposedAnswer, evidence: dict[str, Evidence]
) -> list[dict[str, Any]]:
    payload = []
    for claim in claims:
        for ref in claim.supporting_evidence_ids[:3]:
            receipt = evidence[ref]
            payload.append(
                {
                    "claim": claim.statement,
                    "type": "verified_claim",
                    "title": claim.statement,
                    "game_id": receipt.game_id,
                    "source_name": receipt.source_name,
                    "source_url": receipt.source_url,
                    "metadata": {
                        "claim": claim.model_dump(mode="json"),
                        "evidence_id": ref,
                        **(
                            {
                                "source_type": "possessions",
                                "event_window": receipt.metadata["event_window"],
                                "rows": receipt.metadata["rows"],
                            }
                            if "event_window" in receipt.metadata
                            else {}
                        ),
                    },
                }
            )
    for ref in answer.evidence_ids:
        receipt = evidence[ref]
        payload.append(
            {
                "claim": receipt.text,
                "type": "archive",
                "title": CITATION_TITLES.get(collection(receipt) or "", "Archive receipt"),
                "game_id": receipt.game_id,
                "source_name": receipt.source_name,
                "source_url": receipt.source_url,
                "metadata": {"evidence_id": ref, "source_type": collection(receipt)},
            }
        )
    return payload


_TEXT_LIMIT = 5900


def deterministic_text(claims: list[VerifiedClaim], *, reserve: int = 0) -> str:
    """Complete deterministic wording, bounded by the response text contract.

    `reserve` keeps room for wording that must follow the claims, so appending it never
    pushes the answer past the contract's text bound.
    """
    limit = _TEXT_LIMIT - reserve
    statements: list[str] = []
    for claim in claims:
        candidate = " ".join([*statements, claim.statement])
        if len(candidate) > limit:
            remaining = len(claims) - len(statements)
            statements.append(f"{remaining} further verified claim(s) are cited in this response.")
            break
        statements.append(claim.statement)
    return " ".join(statements)


def coverage_gap(results: list[ToolResult], claims: list[VerifiedClaim]) -> tuple[bool, str]:
    """The explanation for groups a partial answer could not report.

    A comparison can answer one group and have no denominator in another. The answer still
    carries the valid claims and states which group is missing, instead of dropping the
    comparison. Only a result that delivered one of this answer's claims can explain it;
    an unrelated partial tool call is not this turn's story.
    """
    delivered = {claim.claim_id for claim in claims}
    notes: list[str] = []
    for result in results:
        if result.status != "incomplete_coverage" or not result.message:
            continue
        if not delivered.intersection(claim.claim_id for claim in result.claims):
            continue
        notes.append(result.message.strip())
    return bool(notes), " ".join(dict.fromkeys(notes))[:1200]


def disposition(
    results: list[ToolResult], scope: ResolvedQuery | None, *, answered: bool
) -> str | None:
    """Structured disposition of this turn, decided from tool status rather than prose.

    `None` means no decision was reached (for example a dependency failure), which is
    never reported as a refusal.
    """
    if answered:
        return "answer"
    statuses = {result.status for result in results}
    if "ambiguous_entity" in statuses:
        return "clarify"
    if statuses & {"unsupported_metric_or_scope", "no_matching_results"}:
        return "refuse"
    if scope is not None:
        if scope.operation_reason:
            return "refuse"
        if scope.requires_clarification:
            return "clarify"
    return None
