"""One LLM orchestrator, bounded investigation and independent whole-answer review."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_citations import citation_gap
from app.services.analyst_fallback import fallback_claims, re_search_discovery
from app.services.analyst_provider import (
    Schema,
    build_payload,
    encoded,
    request_model,
)
from app.services.analyst_render import (
    citations,
    coverage_gap,
    deterministic_text,
    disposition,
)
from app.services.analyst_tools import AnalystTools
from app.services.conversation_memory import bounded_history
from app.services.evidence_contracts import (
    Action,
    AnswerReview,
    Candidate,
    ClaimUse,
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
        self._traces_seen = 0
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

    @property
    def request_id(self) -> str:
        """The route's request id, shared with the tool layer for retrieval traces."""
        return self.tools.request_id or ""

    @request_id.setter
    def request_id(self, value: str) -> None:
        self.tools.request_id = value

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

    def _record_traces(self) -> None:
        """Append the retrieval traces issued since the last read, in order."""
        pending = self.tools.retrieval_traces[self._traces_seen :]
        self.trace.extend({**item, "stage": "retrieval"} for item in pending)
        self._traces_seen += len(pending)

    async def run(self, *, allow_model: bool = True) -> dict[str, Any]:
        if not allow_model:
            # The configured answer mode intentionally delivers backend facts. That is a
            # complete answer, not an outage, so it is neither degraded nor warned.
            return await self.fallback("", degraded=False)
        failure = None
        try:
            # Leave recovery and response finalization inside the overall request budget.
            investigation_budget = max(0.001, self.remaining() - 2.5)
            try:
                async with asyncio.timeout(investigation_budget):
                    if await self.reserve(3):
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
                    self._record_traces()
                continue
            answer = action.answer
            if answer is None:  # next_action guarantees this; narrows the type
                raise ValueError("Malformed answer action")
            self.last_answer = answer
            supported, reason = await self.validate(answer)
            if supported:
                return self.render(answer, llm=True)
            # One repair; split the remaining time between revision and review.
            repair_timeout = min(
                self.settings.ai_request_timeout_seconds, (self.remaining() - 0.5) / 2
            )
            observed_call_seconds = max(
                (
                    item["latency_ms"] / 1000
                    for item in self.trace
                    if item.get("stage") in {"orchestrate", "revise", "review"}
                ),
                default=1.0,
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
                        return self.render(repaired, llm=True)
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
        gap = citation_gap(self.tools.question, answer, self.sent_evidence)
        if gap:
            return False, gap
        try:
            review = await self.model(
                AnswerReview, review=True, answer=answer, timeout_seconds=timeout_seconds
            )
        except (ValueError, RuntimeError):
            return False, "Reviewer failed or returned malformed output."
        # Claims' backend-issued receipts are legitimate citations even when omitted.
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

    async def fallback(self, reason: str, *, degraded: bool = True) -> dict[str, Any]:
        if not self.fallback_claims() and not self.recovery_ran and self.remaining() > 0.5:
            self.recovery_ran = True
            question = self.tools.question
            comparison = bool(self.tools.scope and self.tools.scope.comparison)
            name = (
                "discover_facts"
                if re_search_discovery(question)
                else "get_team_stats"
                if comparison
                else "get_player_stats"
                if self.tools.scope and self.tools.scope.player_ids
                else "get_team_stats"
            )
            try:
                async with asyncio.timeout(max(0.001, self.remaining() - 0.5)):
                    # Team recovery honours the resolved operation, not just the scope.
                    aggregation = "total" if name == "get_team_stats" else "average"
                    self.results.append(
                        await self.tools.execute(
                            ToolCall(name=name, question=question, aggregation=aggregation)
                        )
                    )
                    self._record_traces()
            except Exception:
                # Cancellation is a BaseException and intentionally propagates.
                pass
        return self.render_fallback(reason, degraded=degraded)

    def render_fallback(self, reason: str, *, degraded: bool = True) -> dict[str, Any]:
        claims = self.fallback_claims()
        partial, coverage = coverage_gap(self.results, claims)
        text = deterministic_text(claims, reserve=(len(coverage) + 1) if coverage else 0)
        if coverage:
            text = f"{text} {coverage}".strip()
        if not text:
            text = next(
                (
                    r.message + (" " + "; ".join(r.choices) if r.choices else "")
                    for r in reversed(self.results)
                ),
                "Verified archive facts are unavailable on this turn. Please try again.",
            )
        if re_search_live(self.tools.question):
            text += " I don't have live injury or current-status updates."
        # The 30-claim cap belongs to a model-authored answer. Deterministic delivery is
        # trusted backend output, so every verified claim is delivered (citations and
        # committed state) while `ProposedAnswer` keeps the model-facing shape unchanged.
        answer = ProposedAnswer(
            text=text,
            claims=[ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in claims[:30]],
        )
        dependency = any(r.status == "dependency_failure" for r in self.results)
        # An intentional deterministic delivery is only complete when it carries verified
        # facts; a dependency failure, an uncovered group or a turn that never ran is a
        # real degradation, while a complete deterministic answer is not an outage.
        degraded = degraded or dependency or partial or (not claims and not self.results)
        if degraded and not reason:
            reason = (
                "Part of this answer's requested coverage could not be reported from the archive."
                if partial
                else "Some archive facts were unavailable on this turn."
            )
        return self.render(
            answer,
            llm=False,
            warning=reason if degraded else "",
            degraded=degraded,
            delivered=claims,
        )

    def render(
        self,
        answer: ProposedAnswer,
        *,
        llm: bool,
        warning: str = "",
        degraded: bool | None = None,
        delivered: list[VerifiedClaim] | None = None,
    ) -> dict[str, Any]:
        # Trusted deterministic delivery may carry every verified claim, independent of the
        # model-facing `ProposedAnswer.claims` cap.
        claims = (
            delivered
            if delivered is not None
            else [self.tools.claims[u.claim_id] for u in answer.claims]
        )
        receipts = citations(claims, answer, self.tools.evidence)
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
        # The private response registry is the committed evidence plus the actual rows
        # each receipt was built from. Production never builds it: its schema excludes it.
        registry = (
            self.tools.provenance.registry(state["evidence"])
            if self.tools.provenance.enabled
            else []
        )
        if degraded is None:
            degraded = not llm
        outcome = self.outcome(answered=bool(claims or (llm and answer.evidence_ids)))
        return {
            "answer": answer.text,
            "follow_up_questions": self.accepted_suggestions if llm else [],
            "citations": receipts,
            "warnings": [warning] if warning else [],
            "degraded": degraded,
            "route": "llm_analyst" if llm else "factual_fallback",
            "data_version": self.tools.release.version,
            "state": state,
            "tool_calls": self.trace,
            "evidence": registry,
            "llm_validated": llm,
            "outcome": outcome,
            # The public flag is the structured disposition, never inferred from wording.
            "refused": outcome == "refuse",
        }

    def outcome(self, *, answered: bool) -> str | None:
        outcome = disposition(self.results, answered=answered)
        if outcome is not None:
            return outcome
        scope = self.tools.scope
        if scope is not None:
            if scope.operation_reason:
                return "refuse"
            if scope.requires_clarification:
                return "clarify"
        return None


def re_search_live(question: str) -> bool:
    return bool(re.search(r"\b(injur\w*|today|current|live|tonight)\b", question, re.I))
