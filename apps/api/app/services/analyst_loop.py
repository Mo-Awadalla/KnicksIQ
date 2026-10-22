"""One LLM orchestrator, bounded investigation and independent whole-answer review."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_delivery import fallback, fallback_claims, render, render_fallback
from app.services.analyst_payload import build_payload
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_provider import (
    Schema,
    encoded,
    request_model,
)
from app.services.analyst_review_checks import review_issues
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
    deterministic_claim_ids,
    split_review_spans,
    validate_review,
    validate_structure,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# The model declares why it is not answering from archive facts. These actions are
# refusals for API consumers even when related archive facts are included.
REFUSAL_ACTIONS = frozenset({"decline", "explain_coverage"})
FACTUAL_REVIEW_TYPES = frozenset({"factual", "interpretation"})


class AnalystLoop:
    def __init__(
        self, tools: AnalystTools, context: list[dict[str, str]], *, started: float | None = None
    ):
        self.tools, self.context = tools, bounded_history(context)
        self.settings = get_settings()
        self.started = started or time.monotonic()
        # Random per-turn id for host routing and prompt caching; never the session token.
        self.session_id = uuid.uuid4().hex
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
        self.preplanned: list[str] = []

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
                    if self.trace:
                        self.trace[-1].update(
                            {
                                "action": action.action,
                                "tools_requested": [tool.name for tool in action.tools],
                            }
                        )
                    return action
                error: Exception = ValueError("Malformed action")
            except ValidationError as exc:
                error = exc
            exhausted = self.calls > self.settings.analyst_max_model_calls - 3
            if retried or exhausted or self.remaining() < 8:
                raise error
            retried = True

    async def run_tool(self, call: ToolCall) -> ToolResult:
        tool_started = time.monotonic()
        result = await self.tools.execute(call)
        self.results.append(result)
        self.trace.append(
            {
                "stage": "tool",
                "tool": call.name,
                "latency_ms": round((time.monotonic() - tool_started) * 1000),
                "status": result.status,
                "claims": len(result.claims),
                "evidence": len(result.evidence),
                "candidates": len(result.candidates),
            }
        )
        return result

    async def prefetch(self) -> None:
        """Run backend-chosen tools before the first model call.

        The orchestrator spends one whole provider round trip choosing a tool that the
        question and the resolved scope already determine. Prefetch removes that call for
        clear questions; the model keeps both tool rounds when the prefetched evidence is
        not enough.
        """
        if not self.settings.analyst_prefetch_enabled:
            return
        # Prefetch exists to replace the planning call on a turn that starts without evidence.
        # When results or committed claims are already present the writer can answer or choose
        # its own tool; a duplicate lookup would only add overlapping claims to the payload.
        if self.results or self.tools.claims:
            return
        calls = prefetch_calls(self.tools)
        if not calls:
            return
        self.preplanned = [call.name for call in calls]
        for call in calls:
            if time.monotonic() - self.started >= self.settings.analyst_investigation_seconds:
                break
            # Prefetched lookups count against the same six-tool limit as model-chosen ones.
            self.tool_count += 1
            await self.run_tool(call)

    async def repair(
        self, answer: ProposedAnswer, reason: str, *, timeout_seconds: float
    ) -> ProposedAnswer | None:
        """Retry an off-schema repair once when two calls stay free, then fail closed.

        The writer intermittently adds a host-format key or a malformed tail; the same
        request usually succeeds, and a schema failure must not discard a backed answer.
        """
        for attempt in range(2):
            try:
                return await self.model(
                    ProposedAnswer,
                    answer=answer,
                    repair=reason,
                    timeout_seconds=timeout_seconds,
                )
            except ValidationError:
                available = sum(slots for _, slots in self.reservations) - self.calls
                if (
                    attempt
                    or self.calls + 2 > self.settings.analyst_max_model_calls
                    or self.remaining() < 2
                    or (available < 2 and not await self.reserve(2 - available))
                ):
                    return None
        return None

    async def investigate(self) -> dict[str, Any]:
        await self.prefetch()
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
                    await self.run_tool(call)
                continue
            answer = action.answer
            if answer is None:  # next_action guarantees this; narrows the type
                raise ValueError("Malformed answer action")
            self.last_answer = answer
            refused = action.action in REFUSAL_ACTIONS
            supported, reason = await self.validate(answer)
            if supported:
                return self.render(answer, llm=True, refused=refused)
            # Split the remaining time between revision and review.
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
                    repaired = await self.repair(answer, reason, timeout_seconds=repair_timeout)
                    if repaired is not None:
                        supported, _ = await self.validate(repaired, timeout_seconds=repair_timeout)
                        if supported:
                            return self.render(repaired, llm=True, refused=refused)
                    else:
                        # Both repair replies were off-schema; this is not a review verdict.
                        return await self.fallback("Repair output did not pass schema validation.")
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
        spans = split_review_spans(answer.text)
        # A reviewer sees each claim's supporting_evidence_ids, so those backend-issued
        # receipts are legitimate citations even when the payload omitted their details.
        reviewable = dict(self.sent_evidence)
        for claim in self.sent_claims.values():
            for ref in claim.supporting_evidence_ids:
                if ref in self.tools.evidence:
                    reviewable.setdefault(ref, self.tools.evidence[ref])
        issues = review_issues(
            answer,
            spans,
            self.sent_claims,
            reviewable,
            self.tools.manifest(),
            self.tools.question,
        )
        if issues:
            # Mechanical rejection before any stochastic reviewer verdict.
            return False, "Deterministic evidence check failed: " + "; ".join(issues[:3])
        review = await self.review(answer, timeout_seconds=timeout_seconds)
        if review is None:
            return False, "Reviewer failed or returned malformed output."
        empty, attachable = self._citation_gaps(review, answer, spans)
        accepted = validate_review(review, answer, self.sent_claims, reviewable, spans=spans)
        metadata = self.trace[-1] if self.trace else {}
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
                self.request_id,
                metadata.get("provider"),
                accepted,
                len(review.assertions),
                len(empty),
                len(attachable),
                extra={
                    "request_id": self.request_id,
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
                self.request_id,
                metadata.get("provider"),
                metadata.get("finish_reason"),
                len(review.assertions),
                len(empty),
                len(attachable),
                unsupported,
                extra={
                    "request_id": self.request_id,
                    "provider": metadata.get("provider"),
                    "finish_reason": metadata.get("finish_reason"),
                    "spans": len(review.assertions),
                    "empty_id_spans": len(empty),
                    "attachable_spans": len(attachable),
                    "unsupported_spans": unsupported,
                },
            )
            return False, encoded(review.model_dump())
        self.accepted_suggestions = accepted_follow_ups(
            review, answer, self.sent_claims, reviewable
        )
        return True, ""

    def _citation_gaps(
        self, review: AnswerReview, answer: ProposedAnswer, spans: list[str]
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
            if deterministic_claim_ids(span, answer, self.sent_claims):
                attachable.append(index)
        return empty, attachable

    async def review(
        self, answer: ProposedAnswer, *, timeout_seconds: float | None = None
    ) -> AnswerReview | None:
        """Review with one retry when the provider returns non-JSON, then fail closed."""
        for attempt in range(2):
            try:
                return await self.model(
                    AnswerReview, review=True, answer=answer, timeout_seconds=timeout_seconds
                )
            except ValidationError:
                capacity = (
                    self.calls < self.settings.analyst_max_model_calls - 2 and self.remaining() > 5
                )
                if attempt or not capacity:
                    return None
            except (ValueError, RuntimeError):
                return None
        return None

    def fallback_claims(self) -> list[VerifiedClaim]:
        return fallback_claims(self)

    async def fallback(self, reason: str) -> dict[str, Any]:
        return await fallback(self, reason)

    def render_fallback(self, reason: str) -> dict[str, Any]:
        return render_fallback(self, reason)

    def render(
        self,
        answer: ProposedAnswer,
        *,
        llm: bool,
        warning: str = "",
        refused: bool = False,
    ) -> dict[str, Any]:
        return render(self, answer, llm=llm, warning=warning, refused=refused)
