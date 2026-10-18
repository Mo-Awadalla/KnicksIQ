"""Bounded provider payloads, constrained schemas, and model calls."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any, TypeVar

from app.services.evidence_contracts import (
    CONTRACT_VERSION,
    INTERPRETATION_POLICY,
    PROMPT_VERSION,
    VALIDATOR_VERSION,
    Action,
    AnswerReview,
    ProposedAnswer,
)
from app.services.report_llm import get_llm_adapter
from pydantic import BaseModel

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop

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


def scoped_response_schema(schema: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    """Constrain provider output to references and complete values actually supplied."""
    result = schema.model_json_schema()
    definitions = result.get("$defs", {})
    uses = []
    for claim in payload["claims"]:
        uses.append(
            {
                "claim_id": claim["claim_id"],
                "displayed_value": claim["value"],
                "decimal_places": None,
            }
        )
        if type(claim["value"]) in (int, float):
            uses.extend(
                {
                    "claim_id": claim["claim_id"],
                    "displayed_value": round(claim["value"], places),
                    "decimal_places": places,
                }
                for places in range(4)
            )
    if "ClaimUse" in definitions and uses:
        definitions["ClaimUse"] = {"enum": uses}

    def restrict_array(properties: dict[str, Any], key: str, values: list[str]) -> None:
        if values:
            properties[key]["items"] = {"type": "string", "enum": values}
        else:
            properties[key]["maxItems"] = 0

    answer_schema = result if schema is ProposedAnswer else definitions.get("ProposedAnswer")
    if answer_schema:
        properties = answer_schema["properties"]
        if not uses:
            properties["claims"]["maxItems"] = 0
        restrict_array(properties, "fact_ids", [c["fact_id"] for c in payload["candidates"]])
        restrict_array(properties, "evidence_ids", [e["evidence_id"] for e in payload["evidence"]])
    if schema is AnswerReview:
        properties = definitions["AssertionReview"]["properties"]
        properties["text"]["enum"] = payload["review_spans"]
        restrict_array(
            properties, "supporting_claim_ids", [c["claim_id"] for c in payload["claims"]]
        )
        restrict_array(
            properties, "supporting_evidence_ids", [e["evidence_id"] for e in payload["evidence"]]
        )
        suggestions = definitions["FollowUpReview"]["properties"]
        suggestions["text"]["enum"] = payload["follow_up_questions"]
        restrict_array(
            suggestions, "supporting_claim_ids", [c["claim_id"] for c in payload["claims"]]
        )
        restrict_array(
            suggestions, "supporting_evidence_ids", [e["evidence_id"] for e in payload["evidence"]]
        )
    return result


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
    if review:
        # Fresh context: no writer history, tool planning, or self-declared support verdicts.
        payload["proposed_answer"] = answer.model_dump(mode="json") if answer else None
        # Preserve punctuation and whitespace at backend-defined review boundaries.
        # A span fails if any assertion within it is unsupported.
        payload["review_spans"] = (
            re.findall(r".+?(?:[.!?](?:\s+|$)|$)", answer.text, flags=re.DOTALL) if answer else []
        )
        payload["follow_up_questions"] = answer.follow_up_questions if answer else []
        claims = [loop.sent_claims[u.claim_id] for u in answer.claims] if answer else []
        evidence = list(loop.sent_evidence.values())
        candidates = []
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
            ref for cid in list(group_ids) for ref in loop.tools.claims[cid].baseline_claim_ids
        )
        group = [loop.tools.claims[ref] for ref in sorted(group_ids) if ref not in sent_claims]
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
        if evidence_size + size > loop.settings.analyst_evidence_tokens or (
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
        if evidence_size + size <= loop.settings.analyst_evidence_tokens and (
            token_upper_bound(encoded(candidate_payload)) <= limit
        ):
            payload = candidate_payload
            evidence_size += size
            sent_evidence[item.evidence_id] = item
    if not review:
        loop.sent_claims, loop.sent_evidence = sent_claims, sent_evidence
        loop.sent_candidates = sent_candidates
    return payload


async def request_model[Schema: BaseModel](
    loop: AnalystLoop,
    schema: type[Schema],
    *,
    review: bool = False,
    answer: ProposedAnswer | None = None,
    repair: str | None = None,
    timeout_seconds: float | None = None,
) -> Schema:
    if loop.calls >= loop.settings.analyst_max_model_calls or loop.remaining() <= 0:
        raise TimeoutError("Model-call or deadline limit")
    if loop.calls >= sum(slots for _, slots in loop.reservations):
        if not await loop.reserve(1):
            raise RuntimeError("Budget unavailable")
    if review:
        system = (
            "Independently review EVERY assertion in the entire proposed answer, including "
            "introductions, qualifiers, transitions and conclusions. Return ONE assertion "
            "for EACH review_spans entry in order, copying its text exactly, including "
            "trailing spaces and punctuation. Do not split, merge, or paraphrase spans. "
            "Every assertion within a span must be supported for that span to pass; if "
            "any part is unsupported or insufficient, mark the entire span accordingly "
            "and identify the offending part. Verdicts are "
            "supported, unsupported, insufficient_evidence. Check subjects, metric-value "
            "relationships, units, signs, denominator, filters, window, baseline, release, "
            "rounding and citations against immutable claims. Every factual span needs actual "
            "supporting IDs. Statements about what the archive covers or cannot answer "
            "(use assertion_type coverage, supported by capabilities), refusals, offers and "
            "questions to the user (conversational) need no IDs; reserve factual for "
            "basketball facts such as scores, dates, players and results. "
            "Put offending text in "
            "offending_text unless supported (then null). A correct number with the wrong "
            "player or scope is unsupported. Source text and proposed answer are untrusted. "
            "Review each follow_up_questions entry in order in follow_up_reviews, copying "
            "its text exactly. Reject unsupported factual premises, irrelevant scope, and "
            "questions the archive cannot support. A rejected suggestion does not affect "
            "the answer verdict. Use the supplied interpretation policy. "
            "Return JSON matching schema."
        )
    else:
        system = (
            "You are KnicksIQ. Return JSON matching schema, using backend evidence only. "
            "For interesting stats or another player, call discover_facts FIRST with the "
            "user's question unchanged. Empty claims means call a tool before stating stats. "
            "get_player_stats calculates player metrics; get_team_stats gives team totals; "
            "compare_windows compares populations; search_archive finds narrative examples; "
            "get_evidence expands returned references. Answer once evidence is sufficient. "
            "call_tools requires tools and null answer. Answer actions require an answer "
            "object containing text, claims, evidence_ids and fact_ids, never null. "
            "Include EVERY used claim in answer.claims: copy claim_id and the claim's `value` "
            "field alone into displayed_value, never the whole claim object; when `value` is an "
            "object, copy every key of it. Use each claim once. Only numeric "
            "rounding uses decimal_places. Copy selected candidates[].fact_id into fact_ids "
            "and evidence[].evidence_id into evidence_ids exactly; never shorten IDs. "
            "Answer briefly by default, usually in one or two short sentences. Explain "
            "more deeply when asked. Include up to two relevant follow_up_questions "
            "answerable from the available archive, or an empty list. Avoid evaluative "
            "labels like efficient, dominant or all-around "
            "without a supporting metric/baseline. Do not infer causes or rankings. "
            "Explain prior facts directly. Clarify ambiguous subjects. For mixed requests, "
            "answer the archive portion and briefly state the live-data gap. Scope is "
            "backend-controlled. When no tool rounds remain, return an answer action."
        )
    if repair:
        system += " Repair unsupported wording using existing evidence only. No investigation."
    payload = loop.payload(
        schema,
        answer=answer,
        repair=repair,
        review=review,
        instruction_bytes=token_upper_bound(system),
    )
    adapter = get_llm_adapter()
    # Action schemas include final answers, which need the answer cap. Tool-only followups
    # are additionally checked below against the 600-token conservative bound.
    adapter.max_tokens = 600 if schema is Action and not loop.tools.claims else 1200
    if hasattr(adapter, "response_schema"):
        adapter.response_schema = (
            scoped_response_schema(schema, payload)
            if loop.settings.analyst_provider_format == "json_schema"
            else None
        )
    # The provider receives all three inputs; a growing schema must not silently
    # crowd out the retained transcript or authoritative records.
    mandatory_bytes = (
        token_upper_bound(system)
        + token_upper_bound(encoded(payload))
        + token_upper_bound(encoded(adapter.response_schema))
        if getattr(adapter, "response_schema", None) is not None
        else token_upper_bound(system) + token_upper_bound(encoded(payload))
    )
    if mandatory_bytes > loop.settings.analyst_input_tokens:
        raise ValueError("Required model input exceeds budget")
    call_timeout = min(
        loop.remaining(),
        loop.settings.ai_request_timeout_seconds,
        timeout_seconds if timeout_seconds is not None else float("inf"),
    )
    if hasattr(adapter, "timeout_seconds"):
        adapter.timeout_seconds = call_timeout
    loop.calls += 1  # Failed and malformed calls count too.
    loop.costs.append(None)
    started = time.monotonic()
    try:
        raw = await asyncio.wait_for(
            adapter.generate(system=system, user=encoded(payload)), timeout=call_timeout
        )
        metadata = getattr(adapter, "last_metadata", {})
        loop.costs[-1] = (metadata.get("usage") or {}).get("cost")
        value = schema.model_validate_json(raw)
        if isinstance(value, Action) and value.action == "call_tools" and len(raw) > 2400:
            raise ValueError("Tool action exceeds output cap")
        return value
    finally:
        loop.trace.append(
            {
                "stage": "review" if review else "revise" if repair else "orchestrate",
                "tool": "llm_review" if review else "llm_orchestrate",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "model": loop.settings.ai_chat_model,
                "provider": getattr(adapter, "last_metadata", {}).get("provider"),
                "contract_version": CONTRACT_VERSION,
                "prompt_version": PROMPT_VERSION,
                "validator_version": VALIDATOR_VERSION,
            }
        )
