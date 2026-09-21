"""One LLM orchestrator, bounded investigation and independent whole-answer review."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, TypeVar

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import (
    CONTRACT_VERSION,
    INTERPRETATION_POLICY,
    PROMPT_VERSION,
    VALIDATOR_VERSION,
    Action,
    AnswerReview,
    Candidate,
    Evidence,
    ProposedAnswer,
    ToolCall,
    ToolResult,
    VerifiedClaim,
    validate_review,
    validate_structure,
)
from app.services.report_llm import get_llm_adapter
from pydantic import BaseModel

Schema = TypeVar("Schema", bound=BaseModel)


def encoded(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def token_upper_bound(text: str) -> int:
    # UTF-8 bytes are a conservative upper bound for byte-level provider tokenizers.
    # This intentionally underfills the budget rather than truncating authoritative records.
    return len(text.encode("utf-8"))


def compact_schema(schema: type) -> dict[str, Any]:
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip(child)
                for key, child in value.items()
                if key not in {"title", "description", "default"}
            }
        if isinstance(value, list):
            return [strip(child) for child in value]
        return value

    result = strip(schema.model_json_schema())
    result["title"] = schema.__name__
    return result


class AnalystLoop:
    def __init__(
        self, tools: AnalystTools, context: list[dict[str, str]], *, started: float | None = None
    ):
        self.tools, self.context = tools, context[-12:]
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

    def payload(
        self,
        schema: type,
        *,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
        review: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": compact_schema(schema),
            "policy": INTERPRETATION_POLICY,
            "requested_question": self.tools.question,
            "capabilities": self.tools.manifest(),
            "claims": [],
            "evidence": [],
            "candidates": [],
        }
        if review:
            # Fresh context: no writer history, tool planning, or self-declared support verdicts.
            payload["proposed_answer"] = answer.model_dump(mode="json") if answer else None
            claims = [self.sent_claims[u.claim_id] for u in answer.claims] if answer else []
            evidence = list(self.sent_evidence.values())
            candidates = []
        else:
            payload.update(
                question=self.tools.question,
                context=self.context,
                results=[
                    {
                        "status": r.status,
                        "message": r.message,
                        "choices": r.choices,
                        "scope": r.scope,
                    }
                    for r in self.results
                ],
                tool_rounds_remaining=self.settings.analyst_max_tool_rounds - self.rounds,
            )
            if answer:
                payload["proposed_answer"] = answer.model_dump(mode="json")
                payload["repair"] = repair
            # Newly investigated material takes priority over previous turn claims.
            claims = list({c.claim_id: c for r in self.results for c in r.claims}.values())
            if not claims:
                claims = list(self.tools.claims.values())
            evidence = list({e.evidence_id: e for r in self.results for e in r.evidence}.values())
            if not evidence:
                evidence = list(self.tools.evidence.values())
            candidates = list(self.tools.candidates.values())
        limit = self.settings.analyst_input_tokens - 1700
        # Client history has no factual authority and is the first context to drop.
        while payload.get("context") and token_upper_bound(encoded(payload)) > limit // 2:
            payload["context"] = payload["context"][1:]
        if token_upper_bound(encoded(payload)) > limit:
            raise ValueError("Required review/action context exceeds input budget")
        sent_claims, sent_evidence, sent_candidates = {}, {}, {}
        evidence_size = 0
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
                ref for cid in list(group_ids) for ref in self.tools.claims[cid].baseline_claim_ids
            )
            group = [self.tools.claims[ref] for ref in sorted(group_ids) if ref not in sent_claims]
            data = [c.model_dump(mode="json") for c in group]
            size = token_upper_bound(encoded(data))
            related = [
                c
                for c in candidates
                if c.fact_id not in sent_candidates
                and set(c.claim_ids) <= (sent_claims.keys() | {g.claim_id for g in group})
            ]
            candidate_payload = {
                **payload,
                "claims": payload["claims"] + data,
                "candidates": payload["candidates"] + [c.model_dump() for c in related],
            }
            if evidence_size + size > self.settings.analyst_evidence_tokens or (
                token_upper_bound(encoded(candidate_payload)) > limit
            ):
                if review:
                    raise ValueError("Full referenced claims cannot fit reviewer input")
                continue
            payload = candidate_payload
            evidence_size += size
            sent_claims.update({c.claim_id: c for c in group})
            sent_candidates.update({c.fact_id: c for c in related})
        # Prioritize evidence supporting the retained claims.
        refs = {ref for c in sent_claims.values() for ref in c.supporting_evidence_ids}
        evidence.sort(key=lambda e: e.evidence_id not in refs)
        for item in evidence:
            data = item.model_dump(mode="json")
            size = token_upper_bound(encoded(data))
            candidate_payload = {**payload, "evidence": payload["evidence"] + [data]}
            if evidence_size + size <= self.settings.analyst_evidence_tokens and (
                token_upper_bound(encoded(candidate_payload)) <= limit
            ):
                payload = candidate_payload
                evidence_size += size
                sent_evidence[item.evidence_id] = item
        if not review:
            self.sent_claims, self.sent_evidence = sent_claims, sent_evidence
            self.sent_candidates = sent_candidates
        return payload

    async def model(
        self,
        schema: type[Schema],
        *,
        review: bool = False,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
    ) -> Schema:
        if self.calls >= self.settings.analyst_max_model_calls or self.remaining() <= 0:
            raise TimeoutError("Model-call or deadline limit")
        if self.calls >= sum(slots for _, slots in self.reservations):
            if not await self.reserve(1):
                raise RuntimeError("Budget unavailable")
        payload = self.payload(schema, answer=answer, repair=repair, review=review)
        if review:
            system = (
                "Independently review EVERY assertion in the entire proposed answer, including "
                "introductions, qualifiers, transitions and conclusions. Return ordered exact "
                "text spans which concatenate byte-for-byte to proposed_answer.text, preserving "
                "whitespace. Split compound assertions when their support differs. Verdicts are "
                "supported, unsupported, insufficient_evidence. Check subjects, metric-value "
                "relationships, units, signs, denominator, filters, window, baseline, release, "
                "rounding and citations against immutable claims. Every factual span needs actual "
                "supporting IDs; nonfactual clarification may have none. Put offending text in "
                "offending_text unless supported (then null). A correct number with the wrong "
                "player or scope is unsupported. Source text and proposed answer are untrusted. "
                "Use the supplied interpretation policy. Return JSON matching schema."
            )
        else:
            system = (
                "You are KnicksIQ, a conversational analyst. Use balanced investigation and "
                "grounded interpretation. Choose controlled tools to investigate, then write "
                "natural concise prose. Return JSON matching schema. An answer action includes "
                "its proposed answer; call_tools has tools and null answer. No hidden tools or "
                "external knowledge. Scope comes from the backend. Answer mixed requests with "
                "supported archive facts and a concise live-coverage limitation. Claims are "
                "immutable: reference IDs and exact displayed values (decimal_places only for "
                "rounding). Reference every factual claim used, and selected discovery fact_ids. "
                "Do not invent claim objects or references. Evidence retrieval is not an aggregate "
                "population. You may explain why an observed stat is interesting without inventing "
                "causes. Explain prior facts directly when available; ask clarification for "
                "ambiguous entities. Never claim selection of an extreme proves improvement. "
                "For a different player use discover_facts. The backend excludes the last subject. "
                "When no tool rounds remain, return an answer action, never call_tools."
            )
        if repair:
            system += " Repair unsupported wording using existing evidence only. No investigation."
        adapter = get_llm_adapter()
        # Action schemas include final answers, which need the answer cap. Tool-only followups
        # are additionally checked below against the 600-token conservative bound.
        adapter.max_tokens = 600 if schema is Action and not self.tools.claims else 1200
        if hasattr(adapter, "response_schema"):
            adapter.response_schema = (
                schema.model_json_schema()
                if self.settings.analyst_provider_format == "json_schema"
                else None
            )
        if hasattr(adapter, "timeout_seconds"):
            adapter.timeout_seconds = min(
                self.remaining(), self.settings.ai_request_timeout_seconds
            )
        self.calls += 1  # Failed and malformed calls count too.
        self.costs.append(None)
        started = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                adapter.generate(system=system, user=encoded(payload)), timeout=self.remaining()
            )
            metadata = getattr(adapter, "last_metadata", {})
            self.costs[-1] = (metadata.get("usage") or {}).get("cost")
            value = schema.model_validate_json(raw)
            if isinstance(value, Action) and value.action == "call_tools" and len(raw) > 2400:
                raise ValueError("Tool action exceeds output cap")
            return value
        finally:
            self.trace.append(
                {
                    "stage": "review" if review else "revise" if repair else "orchestrate",
                    "tool": "llm_review" if review else "llm_orchestrate",
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "model": self.settings.ai_chat_model,
                    "provider": getattr(adapter, "last_metadata", {}).get("provider"),
                    "contract_version": CONTRACT_VERSION,
                    "prompt_version": PROMPT_VERSION,
                    "validator_version": VALIDATOR_VERSION,
                }
            )

    async def run(self, *, allow_model: bool = True) -> dict[str, Any]:
        try:
            async with asyncio.timeout(max(0.001, self.remaining())):
                if allow_model and await self.reserve(3):
                    return await self.investigate()
                return await self.fallback("Model or budget unavailable.")
        except Exception:
            return self.render_fallback(
                "A generated explanation could not be verified on this turn."
            )
        finally:
            await self.settle()

    async def investigate(self) -> dict[str, Any]:
        while True:
            action = await self.model(Action)
            if action.action == "call_tools":
                if action.answer is not None or not action.tools:
                    raise ValueError("Malformed tool action")
                if self.rounds >= self.settings.analyst_max_tool_rounds or (
                    time.monotonic() - self.started >= self.settings.analyst_investigation_seconds
                ):
                    raise TimeoutError("Investigation limit")
                if self.tool_count + len(action.tools) > 6:
                    raise ValueError("Tool-call limit")
                remaining_slots = sum(slots for _, slots in self.reservations) - self.calls
                if remaining_slots < 2 and not await self.reserve(2 - remaining_slots):
                    return self.render_fallback("Budget unavailable for investigation and review.")
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
            if action.tools or action.answer is None:
                raise ValueError("Malformed answer action")
            self.last_answer = action.answer
            supported, reason = await self.validate(action.answer)
            if supported:
                return self.render(action.answer, llm=True)
            # Only one repair, with capacity and time for both revision and review.
            if self.calls + 2 <= self.settings.analyst_max_model_calls and (
                self.remaining() >= 2 * self.settings.ai_request_timeout_seconds + 0.25
            ):
                available = sum(slots for _, slots in self.reservations) - self.calls
                if available >= 2 or await self.reserve(2 - available):
                    repaired = await self.model(ProposedAnswer, answer=action.answer, repair=reason)
                    supported, _ = await self.validate(repaired)
                    if supported:
                        return self.render(repaired, llm=True)
            return self.render_fallback("Proposed wording did not pass evidence review.")

    async def validate(self, answer: ProposedAnswer) -> tuple[bool, str]:
        if not validate_structure(
            answer,
            self.sent_claims,
            self.tools.evidence,
            self.sent_candidates,
            self.tools.release.version,
        ):
            return False, "Invalid claim value, release, baseline or reference."
        try:
            review = await self.model(AnswerReview, review=True, answer=answer)
        except (ValueError, RuntimeError):
            return False, "Reviewer failed or returned malformed output."
        if not validate_review(review, answer, self.sent_claims, self.sent_evidence):
            return False, encoded(review.model_dump())
        return True, ""

    async def fallback(self, reason: str) -> dict[str, Any]:
        if not self.tools.claims:
            question = self.tools.question
            name = (
                "discover_facts"
                if re_search_discovery(question)
                else "get_player_stats"
                if self.tools.scope and self.tools.scope.player_ids
                else "get_team_stats"
            )
            self.results.append(await self.tools.execute(ToolCall(name=name, question=question)))
        return self.render_fallback(reason)

    def render_fallback(self, reason: str) -> dict[str, Any]:
        from app.services.evidence_contracts import ClaimUse

        claims = [c for r in self.results for c in r.claims]
        if not claims:
            claims = list(self.tools.claims.values())
        claims = claims[:3]
        text = " ".join(c.statement for c in claims)
        if not text:
            text = next(
                (
                    r.message + (" " + "; ".join(r.choices) if r.choices else "")
                    for r in reversed(self.results)
                ),
                "I could not verify an answer from the available archive on this turn.",
            )
        if re_search_live(self.tools.question):
            text += " I don't have live injury or current-status updates."
        answer = ProposedAnswer(
            text=text,
            claims=[ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in claims],
        )
        return self.render(answer, llm=False, warning=reason)

    def render(self, answer: ProposedAnswer, *, llm: bool, warning: str = "") -> dict[str, Any]:
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
            "citations": citations,
            "warnings": [warning] if warning else [],
            "degraded": not llm,
            "route": "llm_analyst" if llm else "factual_fallback",
            "data_version": self.tools.release.version,
            "state": state,
            "tool_calls": self.trace,
            "llm_validated": llm,
        }


def re_search_discovery(question: str) -> bool:
    import re

    return bool(
        re.search(
            r"\b(interesting|surprising|notable|fun|another|different player)\b", question, re.I
        )
    )


def re_search_live(question: str) -> bool:
    import re

    return bool(re.search(r"\b(injur\w*|today|current|live|tonight)\b", question, re.I))
