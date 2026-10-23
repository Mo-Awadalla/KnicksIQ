"""Model-facing claim views and the budgeted provider payload."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.analyst_native import paired_record_claims, required_claim_groups
from app.services.analyst_wire import (
    _pack_claims,
    _pack_evidence,
    _wire_payload,
    compact_schema,
    encoded,
    payload_claims,
    payload_evidence,
    scoped_response_schema,
    token_upper_bound,
)
from app.services.evidence_contracts import (
    INTERPRETATION_POLICY,
    ProposedAnswer,
    VerifiedClaim,
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


def build_payload(
    loop: AnalystLoop,
    schema: type,
    *,
    answer: ProposedAnswer | None = None,
    repair: str | None = None,
    review: bool = False,
    instruction_bytes: int = 1700,
) -> dict[str, Any]:
    capabilities = loop.tools.manifest()
    capabilities["scope"] = {
        key: value
        for key, value in capabilities["scope"].items()
        if value is not None and value != []
    }
    # ToolCall schema enumerates these metrics in both provider formats.
    capabilities.pop("metrics", None)
    capabilities.pop("team_metrics", None)
    payload: dict[str, Any] = {
        "schema": (
            {"title": schema.__name__}
            if loop.settings.analyst_provider_format == "json_schema"
            else compact_schema(schema)
        ),
        "policy": INTERPRETATION_POLICY,
        "requested_question": loop.tools.question,
        "capabilities": capabilities,
        "claims": [],
        "claim_context": {},
        "claim_context_format": (
            "Claims/evidence inherit claim_context/evidence_context; row overrides."
        ),
        "evidence": [],
        "evidence_context": {},
        "candidates": [],
    }
    if answer:
        payload["claim_context_format"] += (
            " Proposed uses=[index,precision]; value=claim.value unless value_overrides[index]."
        )
    if review:
        # Fresh context: no writer history, tool planning, or self-declared support verdicts.
        # Complete claim records supply scope, population and metric authority.
        # The reviewer needs coverage limits, not the writer's tool-planning manifest.
        payload["capabilities"] = {key: capabilities[key] for key in ("release_id", "known_gaps")}
        if loop.settings.analyst_provider_format == "json_schema":
            payload["review_support_indexes"] = True
            payload["claim_context_format"] += (
                " Review supporting_claim_ids/supporting_evidence_ids contain 0-based"
                " claims/evidence row indexes; backend restores exact IDs."
            )
        # Text and suggestions are supplied exactly once below. Keep every
        # declared value and citation here; do not duplicate whole-answer prose
        # beside review_spans and its scoped-schema enum.
        if answer:
            declared = answer.model_dump(mode="json", exclude={"text", "follow_up_questions"})
            for use in declared["claims"]:
                if use["decimal_places"] is None:
                    use.pop("decimal_places")
            for key in ("evidence_ids", "fact_ids"):
                if not declared[key]:
                    declared.pop(key)
            payload["proposed_answer"] = declared
        else:
            payload["proposed_answer"] = None
        # Preserve punctuation and whitespace at backend-defined review boundaries.
        # A span fails if any assertion within it is unsupported.
        payload["review_spans"] = (
            re.findall(r".+?(?:[.!?](?:\s+|$)|$)", answer.text, flags=re.DOTALL) if answer else []
        )
        payload["follow_up_questions"] = answer.follow_up_questions if answer else []
        payload["claim_context_format"] += (
            " span_index/follow_up_index=first matching review_spans/follow_up_questions"
            " index (0-based); restores exact text."
        )
        claims = [loop.sent_claims[u.claim_id] for u in answer.claims] if answer else []
        evidence = list(loop.sent_evidence.values())
        candidates = []
    else:
        if loop.results:
            # Each result carries its own resolved scope; repeating the turn scope in
            # capabilities would duplicate the largest planning object.
            capabilities.pop("scope", None)
        payload.update(
            context=loop.context,
            claim_uses=[],
            results=[
                {
                    "status": r.status,
                    "message": r.message,
                    "choices": r.choices,
                    "scope": {
                        key: value
                        for key, value in r.scope.items()
                        if value not in (None, [], {}, False)
                    },
                }
                for r in loop.results
            ],
            tool_rounds_remaining=loop.settings.analyst_max_tool_rounds - loop.rounds,
        )
        if schema is ProposedAnswer:
            # A final writer cannot plan tools; complete native claims retain
            # the actual selected population, scope and release authority.
            payload["capabilities"] = {
                key: capabilities[key] for key in ("release_id", "known_gaps")
            }
            payload.pop("tool_rounds_remaining")
        if answer:
            payload["proposed_answer"] = answer.model_dump(mode="json")
            payload["repair"] = repair
        # Newly investigated material takes priority over previous turn claims.
        claims = list({c.claim_id: c for r in loop.results for c in r.claims}.values())
        if not claims:
            claims = list(loop.tools.claims.values())
        evidence_by_id = {e.evidence_id: e for r in loop.results for e in r.evidence}
        # Current discovery remains useful when a tool result is too large to send.
        # Do not revive unrelated evidence hydrated from earlier conversation turns.
        if loop.tools.discovery:
            for item in loop.tools.discovery.evidence:
                evidence_by_id.setdefault(item.evidence_id, item)
        evidence = list(evidence_by_id.values())
        if not evidence:
            evidence = list(loop.tools.evidence.values())
        candidates = list(loop.tools.candidates.values())

    requirements = required_claim_groups(loop) if not review else {}
    required_groups = [domain for groups in requirements.values() for domain in groups]
    if len(required_groups) > 30:
        raise ValueError("Complete required claims exceed the native answer limit")

    def set_required_indexes(candidate_payload: dict[str, Any]) -> None:
        if not required_groups:
            return
        supplied = payload_claims(candidate_payload)
        if not supplied:
            # Before claim admission there is nothing to select; the sealed index block
            # and its protocol annotation would be pure overhead.
            candidate_payload.pop("required_claim_indexes", None)
            candidate_payload.pop("related_claim_indexes", None)
            return
        candidate_payload["required_claim_indexes"] = [
            [index for index, claim in enumerate(supplied) if claim["claim_id"] in domain]
            for domain in required_groups
        ]
        required_ids = set().union(*required_groups)
        optional = [
            index for index, claim in enumerate(supplied) if claim["claim_id"] not in required_ids
        ]
        candidate_payload.pop("related_claim_indexes", None)
        if optional and "extreme" not in requirements and len(required_groups) < 30:
            candidate_payload["related_claim_indexes"] = optional

    set_required_indexes(payload)

    def input_size(candidate_payload: dict[str, Any]) -> int:
        wire = _wire_payload(candidate_payload)
        response_schema = scoped_response_schema(schema, candidate_payload)
        if loop.settings.analyst_provider_format == "json_object" and (
            review or candidate_payload.get("required_claim_indexes")
        ):
            # The sealed-index contract must be advertised exactly where it is emitted.
            wire["schema"] = response_schema
        size = instruction_bytes + token_upper_bound(encoded(wire))
        if loop.settings.analyst_provider_format == "json_schema":
            size += token_upper_bound(encoded(response_schema))
        return size

    if input_size(payload) > loop.settings.analyst_input_tokens:
        raise ValueError("Required review/action context exceeds input budget")
    sent_claims: dict[str, VerifiedClaim] = {}
    sent_evidence = {}
    sent_candidates = {}
    record_ids = {claim.claim_id for claim in paired_record_claims(loop)}
    narrative_ids = {
        c.claim_id
        for result in loop.results
        for c in result.claims
        if loop.tools.narrative
        and (
            c.metric_id == "canonical_game_narrative"
            or (
                loop.tools.statistical_extreme_requested()
                and c.metric_id in {"game_score", "margin"}
            )
        )
    }
    profile_ids = {
        claim.claim_id
        for claim in loop.fallback_claims()
        if loop.tools.scope
        and loop.tools.scope.player_ids
        and not (loop.tools.scope.metric or loop.tools.scope.requested_metrics)
        and loop.tools.player_profile_requested()
    }
    for claim in claims:
        # Claim groups remain indivisible. Whole optional source details may be
        # omitted: complete provenance IDs remain resolvable in the native registry.
        candidate_refs = {
            ref
            for candidate in candidates
            if claim.claim_id in candidate.claim_ids
            for ref in candidate.claim_ids
        }
        group_ids = {claim.claim_id, *candidate_refs}
        if not review:
            # Baseline and companion groups are authoritative server-side. The reviewer
            # judges the declared assertions only; repeating undeclared provenance in the
            # bounded review wire can evict the declared receipts.
            group_ids.update(claim.baseline_claim_ids)
            if claim.claim_id in record_ids:
                group_ids.update(record_ids)
            if claim.claim_id in narrative_ids:
                group_ids.update(narrative_ids)
            if claim.claim_id in profile_ids:
                group_ids.update(profile_ids)
            group_ids.update(
                ref for cid in list(group_ids) for ref in loop.tools.claims[cid].baseline_claim_ids
            )
        group = [loop.tools.claims[ref] for ref in sorted(group_ids) if ref not in sent_claims]
        data = [c.model_dump(mode="json") for c in group]
        uses = [{"claim_id": c.claim_id, "displayed_value": c.value} for c in group]
        related = [
            c
            for c in candidates
            if c.fact_id not in sent_candidates
            and set(c.claim_ids) <= (sent_claims.keys() | {g.claim_id for g in group})
        ]
        candidate_payload = {
            **payload,
            "claims": payload_claims(payload) + data,
            "candidates": payload["candidates"] + [c.model_dump() for c in related],
        }
        if not review:
            candidate_payload["claim_uses"] = payload["claim_uses"] + uses
            set_required_indexes(candidate_payload)
        _pack_claims(candidate_payload, candidate_payload["claims"])
        if review:
            candidate_payload["capabilities"] = {
                "release_id": capabilities["release_id"],
                "known_gaps": capabilities["known_gaps"],
            }
            if all(
                entry["release_id"] == capabilities["release_id"]
                for entry in payload_claims(candidate_payload)
            ):
                # Identical release authority remains in every immutable record.
                candidate_payload["capabilities"].pop("release_id")
        candidate_wire = _wire_payload(candidate_payload)
        size = token_upper_bound(
            encoded(
                {
                    key: candidate_wire[key]
                    for key in (
                        "claim_context",
                        "statement_context",
                        "eligibility_context",
                        "claims",
                        "claim_uses",
                        "required_claim_indexes",
                        "related_claim_indexes",
                    )
                    if key in candidate_wire
                }
            )
        )
        if size > loop.settings.analyst_evidence_tokens or (
            input_size(candidate_payload) > loop.settings.analyst_input_tokens
        ):
            if review:
                raise ValueError("Full referenced claims cannot fit reviewer input")
            continue
        payload = candidate_payload
        sent_claims.update({c.claim_id: c for c in group})
        sent_candidates.update({c.fact_id: c for c in related})
    if not review and not record_ids <= sent_claims.keys():
        raise ValueError("Complete requested record exceeds model input budget")
    if not review and not narrative_ids <= sent_claims.keys():
        # A partial selection cannot pass completeness validation. Preserve
        # every backend claim without paying for a known-incomplete prompt.
        raise ValueError("Complete selected-game claims exceed model input budget")
    if not review and not profile_ids <= sent_claims.keys():
        raise ValueError("Complete requested player profile exceeds model input budget")
    if not review and any(not domain & sent_claims.keys() for domain in required_groups):
        raise ValueError("Complete requested claim requirements exceed model input budget")
    # Prioritize evidence supporting the retained claims.
    refs = {ref for c in sent_claims.values() for ref in c.supporting_evidence_ids}
    if not review:
        # Aggregate receipts live in the registry even when tools return only
        # their raw source rows. Resolve just the retained claims' references.
        evidence_by_id = {item.evidence_id: item for item in evidence}
        for ref in sorted(refs):
            item = loop.tools.evidence.get(ref)
            if item is not None and item.release_id == loop.tools.release.version:
                evidence_by_id.setdefault(ref, item)
        evidence = list(evidence_by_id.values())
    cited = set(answer.evidence_ids) if answer else set()
    priority_sources = cited | {
        ref for cid in profile_ids for ref in loop.tools.claims[cid].supporting_evidence_ids
    }
    evidence.sort(
        key=lambda item: (
            item.evidence_id not in priority_sources,
            item.evidence_id not in refs,
        )
    )
    # Shared receipt metadata can make the complete required group smaller than one
    # receipt admitted alone. Budget the group together instead of dropping its first row.
    required_evidence = [item for item in evidence if item.evidence_id in cited]
    evidence_groups = ([required_evidence] if required_evidence else []) + [
        [item] for item in evidence if item.evidence_id not in cited
    ]
    for evidence_group in evidence_groups:
        item = evidence_group[0]
        if (
            (required_groups or narrative_ids)
            and not review
            and item.evidence_id not in refs
            and item.evidence_id not in priority_sources
        ):
            # Required claim groups and complete selected-game claims have fixed backend
            # evidence. Unrelated sources only fill the input cap and can be cited without
            # leaving room for the reviewer to validate every referenced source.
            continue
        data = [entry.model_dump(mode="json") for entry in evidence_group]
        candidate_payload = {**payload}
        _pack_evidence(candidate_payload, payload_evidence(payload) + data)
        candidate_wire = _wire_payload(candidate_payload)
        size = token_upper_bound(
            encoded(
                {
                    key: candidate_wire[key]
                    for key in (
                        "claim_context",
                        "statement_context",
                        "eligibility_context",
                        "claims",
                        "claim_uses",
                        "required_claim_indexes",
                        "related_claim_indexes",
                        "evidence_context",
                        "evidence",
                    )
                    if key in candidate_wire
                }
            )
        )
        if size <= loop.settings.analyst_evidence_tokens and (
            input_size(candidate_payload) <= loop.settings.analyst_input_tokens
        ):
            payload = candidate_payload
            sent_evidence.update({entry.evidence_id: entry for entry in evidence_group})
    if not cited <= sent_evidence.keys():
        raise ValueError("Complete explicitly cited sources exceed model input budget")
    if not review:
        loop.sent_claims, loop.sent_evidence = sent_claims, sent_evidence
        loop.sent_candidates = sent_candidates
    wire = _wire_payload(payload, complete=True)
    if loop.settings.analyst_provider_format == "json_object" and (
        review or payload.get("required_claim_indexes")
    ):
        wire["schema"] = scoped_response_schema(schema, payload)
    return wire
