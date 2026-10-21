"""One LLM orchestrator, bounded investigation and independent whole-answer review."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_fallback import decline_text, fallback_claims, re_search_discovery
from app.services.analyst_provider import (
    Schema,
    build_payload,
    encoded,
    request_model,
)
from app.services.analyst_tool_registry import recovery_tool
from app.services.analyst_tools import AnalystTools
from app.services.conversation_memory import bounded_history
from app.services.evidence_contracts import (
    Action,
    AnswerReview,
    Candidate,
    Evidence,
    ProposedAnswer,
    ToolCall,
    ToolResult,
    VerifiedClaim,
    accepted_follow_ups,
    validate_review,
    validate_structure,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# The model declares why it is not answering from archive facts. These actions are
# refusals for API consumers even when related archive facts are included.
REFUSAL_ACTIONS = frozenset({"decline", "explain_coverage"})


class AnalystLoop:
    def __init__(
        self, tools: AnalystTools, context: list[dict[str, str]], *, started: float | None = None
    ):
        self.tools, self.context = tools, bounded_history(context)
        self.settings = get_settings()
        self.started = started or time.monotonic()
        self.calls = 0
        self.rounds = 0
        self.tool_count = 0
        self.trace: list[dict[str, Any]] = []
        self.results: list[ToolResult] = []
        self.sent_claims: dict[str, VerifiedClaim] = {}
        self.sent_evidence: dict[str, Evidence] = {}
        self.sent_candidates: dict[str, Candidate] = {}
        self.reservations: list[tuple[BudgetReservation, int]] = []
        self.costs: list[float | None] = []
        self.last_answer: ProposedAnswer | None = None
        self.accepted_suggestions: list[str] = []
        self.recovery_ran = False
        self.request_id = ""

    def payload(
        self,
        schema: type,
        *,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
        review: bool = False,
        instruction_bytes: int = 1700,
    ) -> dict[str, Any]:
        return build_payload(
            self,
            schema,
            answer=answer,
            repair=repair,
            review=review,
            instruction_bytes=instruction_bytes,
        )

    async def model(
        self,
        schema: type[Schema],
        *,
        review: bool = False,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Schema:
        return await request_model(
            self,
            schema,
            review=review,
            answer=answer,
            repair=repair,
            timeout_seconds=timeout_seconds,
        )

    def remaining(self) -> float:
        return self.settings.analyst_deadline_seconds - (time.monotonic() - self.started)

    async def reserve(self, calls: int) -> bool:
        reservation = await BudgetReservation.reserve(
            self.settings.analyst_call_reservation_usd * calls
        )
        if reservation is None:
            return False
        self.reservations.append((reservation, calls))
        return True

    async def settle(self) -> None:
        offset = 0
        for reservation, slots in self.reservations:
            costs = self.costs[offset : offset + slots]
            amount = sum(
                c if c is not None else self.settings.analyst_call_reservation_usd for c in costs
            )
            await reservation.settle(amount)
            offset += slots

    async def run(self, *, allow_model: bool = True) -> dict[str, Any]:
        failure = None
        try:
            # Leave recovery and response finalization inside the overall request budget.
            investigation_budget = max(0.001, self.remaining() - 2.5)
            try:
                async with asyncio.timeout(investigation_budget):
                    if allow_model and await self.reserve(3):
                        return await self.investigate()
            except Exception as exc:
                failure = exc
            result = await self.fallback("Model or budget unavailable.")
            if failure is not None:
                logger.warning(
                    "analyst_execution_failed request_id=%s error_type=%s stage=%s "
                    "recovery_ran=%s recovered_facts=%s",
                    self.request_id,
                    type(failure).__name__,
                    self.trace[-1]["stage"] if self.trace else "admission",
                    self.recovery_ran,
                    bool(result["citations"]),
                    extra={
                        "request_id": self.request_id,
                        "error_type": type(failure).__name__,
                        "stage": self.trace[-1]["stage"] if self.trace else "admission",
                        "model_calls": self.calls,
                        "tool_rounds": self.rounds,
                        "recovery_ran": self.recovery_ran,
                        "recovered_facts": bool(result["citations"]),
                    },
                )
            return result
        finally:
            await self.settle()

    async def next_action(self) -> Action:
        """Return a well-formed action, retrying the model once when it is not.

        The model intermittently returns an off-schema or self-contradictory action and the
        same request usually succeeds. Two calls stay free for the answer and its review.
        """
        retried = False
        while True:
            try:
                action = await self.model(Action)
                if action.action == "call_tools":
                    well_formed = action.answer is None and bool(action.tools)
                else:
                    well_formed = action.answer is not None and not action.tools
                if well_formed:
                    return action
                error: Exception = ValueError("Malformed action")
            except ValidationError as exc:
                error = exc
            exhausted = self.calls > self.settings.analyst_max_model_calls - 3
            if retried or exhausted or self.remaining() < 8:
                raise error
            retried = True

    async def investigate(self) -> dict[str, Any]:
        while True:
            action = await self.next_action()
            if action.action == "call_tools":
                if self.rounds >= self.settings.analyst_max_tool_rounds or (
                    time.monotonic() - self.started >= self.settings.analyst_investigation_seconds
                ):
                    raise TimeoutError("Investigation limit")
                if self.tool_count + len(action.tools) > 6:
                    raise ValueError("Tool-call limit")
                remaining_slots = sum(slots for _, slots in self.reservations) - self.calls
                if remaining_slots < 2 and not await self.reserve(2 - remaining_slots):
                    return await self.fallback("Budget unavailable for investigation and review.")
                self.rounds += 1
                # One AsyncSession cannot run concurrent database operations.
                for call in action.tools:
                    if (
                        time.monotonic() - self.started
                        >= self.settings.analyst_investigation_seconds
                    ):
                        break
                    self.tool_count += 1
                    self.results.append(await self.tools.execute(call))
                continue
            answer = action.answer
            if answer is None:  # next_action guarantees this; narrows the type
                raise ValueError("Malformed answer action")
            self.last_answer = answer
            refused = action.action in REFUSAL_ACTIONS
            supported, reason = await self.validate(answer)
            if supported:
                return self.render(answer, llm=True, refused=refused)
            # Only one repair, with capacity and time for both revision and review.
            # Split remaining time between the calls instead of demanding two full
            # 20-second provider timeouts inside a 30-second application deadline.
            repair_timeout = min(
                self.settings.ai_request_timeout_seconds, (self.remaining() - 0.5) / 2
            )
            observed_call_seconds = max(
                (item["latency_ms"] / 1000 for item in self.trace), default=1.0
            )
            if self.calls + 2 <= self.settings.analyst_max_model_calls and (
                repair_timeout >= max(1.0, observed_call_seconds)
            ):
                available = sum(slots for _, slots in self.reservations) - self.calls
                if available >= 2 or await self.reserve(2 - available):
                    repaired = await self.model(
                        ProposedAnswer,
                        answer=answer,
                        repair=reason,
                        timeout_seconds=repair_timeout,
                    )
                    supported, _ = await self.validate(repaired, timeout_seconds=repair_timeout)
                    if supported:
                        return self.render(repaired, llm=True, refused=refused)
            return await self.fallback("Proposed wording did not pass evidence review.")

    async def validate(
        self, answer: ProposedAnswer, *, timeout_seconds: float | None = None
    ) -> tuple[bool, str]:
        if not validate_structure(
            answer,
            self.sent_claims,
            self.tools.evidence,
            self.sent_candidates,
            self.tools.release.version,
        ):
            return False, (
                "Invalid claim value, release, baseline or reference. displayed_value must equal "
                "the claim's `value` field exactly, not the whole claim object."
            )
        try:
            review = await self.model(
                AnswerReview, review=True, answer=answer, timeout_seconds=timeout_seconds
            )
        except (ValueError, RuntimeError):
            return False, "Reviewer failed or returned malformed output."
        # A reviewer sees each claim's supporting_evidence_ids, so those backend-issued
        # receipts are legitimate citations even when the payload omitted their details.
        reviewable = dict(self.sent_evidence)
        for claim in self.sent_claims.values():
            for ref in claim.supporting_evidence_ids:
                if ref in self.tools.evidence:
                    reviewable.setdefault(ref, self.tools.evidence[ref])
        if not validate_review(review, answer, self.sent_claims, reviewable):
            return False, encoded(review.model_dump())
        self.accepted_suggestions = accepted_follow_ups(
            review, answer, self.sent_claims, reviewable
        )
        return True, ""

    def fallback_claims(self) -> list[VerifiedClaim]:
        return fallback_claims(self)

    async def fallback(self, reason: str) -> dict[str, Any]:
        if not self.fallback_claims() and not self.recovery_ran and self.remaining() > 0.5:
            self.recovery_ran = True
            question = self.tools.question
            spec = recovery_tool(
                "discovery"
                if re_search_discovery(question)
                else "player"
                if self.tools.scope and self.tools.scope.player_ids
                else "team"
            )
            try:
                async with asyncio.timeout(max(0.001, self.remaining() - 0.5)):
                    self.results.append(
                        await self.tools.execute(
                            ToolCall(
                                name=spec.name,
                                question=question,
                                aggregation=spec.recovery_aggregation,
                            )
                        )
                    )
            except Exception:
                # Cancellation is a BaseException and intentionally propagates.
                pass
        return self.render_fallback(reason)

    def render_fallback(self, reason: str) -> dict[str, Any]:
        from app.services.evidence_contracts import ClaimUse

        claims = self.fallback_claims()
        claims = claims[:6]
        text = " ".join(c.statement for c in claims)
        if not text:
            text = decline_text(self)
        answer = ProposedAnswer(
            text=text,
            claims=[ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in claims],
        )
        # The fallback appends this same statement only for live/current questions, so the
        # flag tracks what the delivered text actually says without parsing its wording.
        return self.render(
            answer, llm=False, warning=reason, refused=re_search_live(self.tools.question)
        )

    def render(
        self,
        answer: ProposedAnswer,
        *,
        llm: bool,
        warning: str = "",
        refused: bool = False,
    ) -> dict[str, Any]:
        claims = [self.tools.claims[u.claim_id] for u in answer.claims]
        citations = []
        for claim in claims:
            for ref in claim.supporting_evidence_ids[:3]:
                e = self.tools.evidence[ref]
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
            e = self.tools.evidence[ref]
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
        state = self.tools.state.copy()
        candidates = [self.tools.candidates[ref] for ref in answer.fact_ids]
        used = {c.claim_id for c in claims}
        # Deterministic facts also count as delivered when they make it into a committed response.
        if not llm:
            candidates = [c for c in self.tools.candidates.values() if set(c.claim_ids) <= used]
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
            {
                c.claim_id: c for c in claims + [self.tools.claims[ref] for ref in baseline_ids]
            }.values()
        )
        references.update(ref for c in stored_claims for ref in c.supporting_evidence_ids)
        references.update(
            source
            for ref in list(references)
            for source in self.tools.evidence[ref].metadata.get("source_evidence_ids", [])
        )
        state["claims"] = [c.model_dump(mode="json") for c in stored_claims]
        state["evidence"] = [self.tools.evidence[ref].model_dump(mode="json") for ref in references]
        return {
            "answer": answer.text,
            "follow_up_questions": self.accepted_suggestions if llm else [],
            "citations": citations,
            "warnings": [warning] if warning else [],
            "degraded": not llm,
            "refused": refused,
            "route": "llm_analyst" if llm else "factual_fallback",
            "data_version": self.tools.release.version,
            "state": state,
            "tool_calls": self.trace,
            "llm_validated": llm,
        }
