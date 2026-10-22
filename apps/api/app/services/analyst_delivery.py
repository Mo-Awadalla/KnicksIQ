"""Validated answer delivery, deterministic fallback and committed state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.services.analyst_fallback import (
    decline_text,
    fallback_text,
    future_requested,
    re_search_live,
    recovery_call,
)
from app.services.analyst_fallback import fallback_claims as select_fallback_claims
from app.services.evidence_contracts import ClaimUse, ProposedAnswer, VerifiedClaim

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop


def fallback_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    return select_fallback_claims(loop)


async def fallback(loop: AnalystLoop, reason: str) -> dict[str, Any]:
    if (
        not loop.fallback_claims()
        and not loop.recovery_ran
        and not future_requested(loop.tools.question)
        and not future_requested(loop.tools.topic)
        and loop.remaining() > 0.5
    ):
        loop.recovery_ran = True
        try:
            async with asyncio.timeout(max(0.001, loop.remaining() - 0.5)):
                loop.results.append(await loop.tools.execute(recovery_call(loop.tools)))
        except Exception:
            # Cancellation is a BaseException and intentionally propagates.
            pass
    return loop.render_fallback(reason)


def render_fallback(loop: AnalystLoop, reason: str) -> dict[str, Any]:
    claims = fallback_claims(loop)
    claims = claims[:6]
    text = " ".join(fallback_text(c) for c in claims)
    if not text:
        text = decline_text(loop)
    answer = ProposedAnswer(
        text=text,
        claims=[ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in claims],
    )
    # The fallback appends the live statement only for live/current questions, so the
    # flag tracks what the delivered text actually says without parsing its wording.
    return loop.render(
        answer,
        llm=False,
        warning=reason,
        refused=re_search_live(loop.tools.question)
        or future_requested(loop.tools.question)
        or future_requested(loop.tools.topic),
    )


def render(
    loop: AnalystLoop,
    answer: ProposedAnswer,
    *,
    llm: bool,
    warning: str = "",
    refused: bool = False,
) -> dict[str, Any]:
    claims = [loop.tools.claims[u.claim_id] for u in answer.claims]
    citations = []
    for claim in claims:
        for ref in claim.supporting_evidence_ids[:3]:
            e = loop.tools.evidence[ref]
            citations.append(
                {
                    "claim": claim.statement,
                    "type": "verified_claim",
                    "title": claim.statement,
                    "game_id": e.game_id,
                    "source_name": e.source_name,
                    "source_url": e.source_url,
                    "metadata": {"claim": claim.model_dump(mode="json"), "evidence_id": ref},
                }
            )
    for ref in answer.evidence_ids:
        e = loop.tools.evidence[ref]
        citations.append(
            {
                "claim": e.text,
                "type": "archive",
                "title": "Archive receipt",
                "game_id": e.game_id,
                "source_name": e.source_name,
                "source_url": e.source_url,
                "metadata": {"evidence_id": ref},
            }
        )
    # Only the route's atomic commit makes these proposed state changes authoritative.
    state = loop.tools.state.copy()
    # A turn that delivered no verified claim (and no archive evidence) declined; the next
    # follow-up must keep the last accepted topic and scope instead of the decline text.
    state["declined"] = not claims and not answer.evidence_ids
    candidates = [loop.tools.candidates[ref] for ref in answer.fact_ids]
    used = {c.claim_id for c in claims}
    # Deterministic facts also count as delivered when they make it into a committed response.
    if not llm:
        candidates = [c for c in loop.tools.candidates.values() if set(c.claim_ids) <= used]
    state["delivered_fact_ids"] = list(
        dict.fromkeys(state.get("delivered_fact_ids", []) + [c.fact_id for c in candidates])
    )
    state["delivered_families"] = list(
        dict.fromkeys(state.get("delivered_families", []) + [c.fact_family for c in candidates])
    )
    state["last_subjects"] = list(dict.fromkeys(c.subject_id for c in claims if c.subject_id))
    players = [int(s.split(":")[1]) for s in state["last_subjects"] if s.startswith("player:")]
    if players:
        state["scope"]["player_ids"] = players
        state["scope_origin"] = "delivered_subject"
    references = {ref for c in claims for ref in c.supporting_evidence_ids}
    references.update(answer.evidence_ids)
    baseline_ids = {ref for c in claims for ref in c.baseline_claim_ids}
    stored_claims = list(
        {c.claim_id: c for c in claims + [loop.tools.claims[ref] for ref in baseline_ids]}.values()
    )
    references.update(ref for c in stored_claims for ref in c.supporting_evidence_ids)
    references.update(
        source
        for ref in list(references)
        for source in loop.tools.evidence[ref].metadata.get("source_evidence_ids", [])
    )
    state["claims"] = [c.model_dump(mode="json") for c in stored_claims]
    state["evidence"] = [loop.tools.evidence[ref].model_dump(mode="json") for ref in references]
    return {
        "answer": answer.text,
        "follow_up_questions": loop.accepted_suggestions if llm else [],
        "citations": citations,
        "warnings": [warning] if warning else [],
        "degraded": not llm,
        "refused": refused,
        "route": "llm_analyst" if llm else "factual_fallback",
        "data_version": loop.tools.release.version,
        "state": state,
        "tool_calls": loop.trace,
        "llm_validated": llm,
    }
