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
from app.services.answer_evidence import AnswerEvidence, select_answer_evidence
from app.services.evidence_contracts import ClaimUse, ProposedAnswer, ToolCall, VerifiedClaim

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop


def fallback_claims(loop: AnalystLoop) -> list[VerifiedClaim]:
    # One coverage policy: the merged loop applies native completeness first and only
    # then the PR split/flow families. Selecting the family list directly would reject
    # native claims a disabled-model turn has already prepared.
    return loop.fallback_claims()


async def fallback(loop: AnalystLoop, reason: str) -> dict[str, Any]:
    live_only = (
        (re_search_live(loop.tools.question) or future_requested(loop.tools.question))
        and loop._native_statistic_tool() is None
        and not loop.tools.narrative
        and not loop._has_explicit_archive_scope()
    )
    if (
        not live_only
        and not loop.fallback_claims()
        and not loop.recovery_ran
        and loop.remaining() > 0.5
    ):
        loop.recovery_ran = True
        try:
            async with asyncio.timeout(max(0.001, loop.remaining() - 0.5)):
                call = (
                    ToolCall(name="get_game_narrative", question=loop.tools.question)
                    if loop.tools.narrative
                    else recovery_call(loop.tools)
                )
                loop.results.append(await loop.tools.execute(call))
        except Exception:
            # Cancellation is a BaseException and intentionally propagates.
            pass
    return loop.render_fallback(reason)


def render_fallback(loop: AnalystLoop, reason: str) -> dict[str, Any]:
    claims = fallback_claims(loop)
    text = " ".join(fallback_text(c) for c in claims)
    required = loop._required_claim_groups()
    claim_ids = {claim.claim_id for claim in claims}
    complete_native = bool(required) and all(
        all(domain & claim_ids for domain in groups) for groups in required.values()
    )
    if loop.tools.narrative:
        selected_games = {game.id for game in loop.tools.narrative.games}
        complete_native = complete_native or any(
            claim.metric_id == "canonical_game_narrative"
            and set(claim.game_ids or []) == selected_games
            for claim in claims
        )
    if not complete_native:
        claims = claims[:6]
        text = " ".join(fallback_text(c) for c in claims)
    if not text:
        text = decline_text(loop)
    if re_search_live(loop.tools.question) and "live" not in text.lower():
        # Mixed archive/live turns deliver the archived answer but must still state the gap.
        text += (
            " I don't have live game scores."
            if "score" in loop.tools.question.lower()
            else " I don't have live injury or current-status updates."
        )
    oversized = complete_native and (len(text) > 6000 or len(claims) > 30)
    answer = ProposedAnswer(
        # The model-facing contract is bounded; complete backend-selected populations are not.
        text="Complete verified archive facts follow." if oversized else text,
        claims=(
            []
            if complete_native
            else [ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in claims]
        ),
    )
    live_only = (
        (re_search_live(loop.tools.question) or future_requested(loop.tools.question))
        and loop._native_statistic_tool() is None
        and not loop.tools.narrative
        and not loop._has_explicit_archive_scope()
    )
    response = loop.render(
        answer,
        llm=False,
        warning=reason,
        refused=loop.model_refused or live_only,
        backend_claims=claims if complete_native else None,
    )
    if oversized:
        response["answer"] = text
    return response


def render(
    loop: AnalystLoop,
    answer: ProposedAnswer,
    *,
    llm: bool,
    warning: str = "",
    refused: bool = False,
    backend_claims: list[VerifiedClaim] | None = None,
) -> dict[str, Any]:
    if backend_claims is None:
        selected = select_answer_evidence(
            answer,
            loop.sent_claims if llm else loop.tools.claims,
            loop.sent_evidence if llm else loop.tools.evidence,
            loop.tools.evidence,
        )
        claims = [selected.claims[u.claim_id] for u in answer.claims]
    else:
        selected_claims = {claim.claim_id: claim for claim in backend_claims}
        references = {ref for claim in backend_claims for ref in claim.supporting_evidence_ids}
        selected = AnswerEvidence(
            claims=selected_claims,
            evidence={ref: loop.tools.evidence[ref] for ref in references},
        )
        claims = backend_claims
    citations = []
    for claim in claims:
        for ref in claim.supporting_evidence_ids[:3]:
            e = selected.evidence[ref]
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
        e = selected.evidence[ref]
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
    # A refusal is not an accepted topic even when it cites archive facts as context, and
    # a refusal whose answer failed validation must not become one through its fallback.
    # A turn that delivered no verified claim (and no archive evidence) declined too.
    state["declined"] = refused or loop.model_refused or (not claims and not answer.evidence_ids)
    # A refusal is not an accepted topic. A turn that was degraded for any other reason
    # did resolve the question the user asked, so its topic and scope stay available to
    # the next elliptical turn instead of falling back to an older one.
    if not (refused or loop.model_refused):
        if state.get("intent"):
            state["last_topic"] = state["intent"]
        if state.get("scope"):
            state["last_scope"] = state["scope"]
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
    references = set(selected.evidence)
    stored_claims = list(selected.claims.values())
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
