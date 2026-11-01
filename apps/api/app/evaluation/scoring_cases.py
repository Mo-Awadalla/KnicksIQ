"""Per-case scoring of one recorded observation against its typed expectation.

The case score is fail-closed and disaggregated: every failure code is recorded,
and the mandatory checks are derived from the codes rather than from a separate
enumeration that can disagree. A response whose identity or digest does not verify
cannot contribute a passing measurement. Citations are verified per claim against
that claim's own receipts and the response's backend-issued evidence registry, so
one correct receipt never covers another claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evaluation.assertion_checks import (
    AssertionFailure,
    check_fact,
    numeric_tokens,
)
from app.evaluation.assertions import (
    entity_assertions,
    extra_claims,
    unattributed_numbers,
)
from app.evaluation.labels import ExpectationCase, LabelError, conversation_context
from app.evaluation.mapping import CitationResolution, RuntimeMapping
from app.evaluation.mapping_citation import CalculationContent
from app.evaluation.observations import EvidenceRecord, Observation, canonical_digest
from app.evaluation.reviews import CaseDecision, DecisionRecord

INTEGRITY_CODES = frozenset(
    {
        "response_hash_missing",
        "response_hash_mismatch",
        "malformed_claim",
        "malformed_trace",
        "malformed_evidence_registry",
        "request_identity_missing",
        "request_question_missing",
        "request_season_missing",
        "request_turn_missing",
        "request_revision_missing",
        "turn_identity_missing",
        "turn_identity_mismatch",
        "request_id_missing",
        "response_request_id_mismatch",
        "request_case_mismatch",
        "request_context_missing",
        "request_context_mismatch",
        "trace_rank_invalid",
        "trace_duplicate_evidence",
        "trace_release_mismatch",
        "trace_request_mismatch",
    }
)
FACT_INVALID_CODES = frozenset({"no_typed_claim_for_fact", "malformed_claim"})
NUMERIC_CODES = frozenset(
    {"numeric_mismatch", "unit_mismatch", "release_mismatch", "claim_not_displayed"}
)
SCOPE_CODES = frozenset(
    {
        "scope_mismatch",
        "window_mismatch",
        "denominator_mismatch",
        "scope_not_expressible",
        "evidence_scope_mismatch",
        "evidence_unmapped",
        "season_mismatch",
        "season_unverifiable",
    }
)
ENTITY_CODES = frozenset({"entity_mismatch"})


@dataclass
class CaseScore:
    case: ExpectationCase
    observation: Observation | None
    failures: list[AssertionFailure] = field(default_factory=list)
    checks: dict[str, bool | None] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    reviewed: bool = False
    integrity: bool = True
    citation_blockers: list[str] = field(default_factory=list)
    entity_blockers: list[str] = field(default_factory=list)
    assertion_blockers: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.observation is None or not self.integrity:
            return "fail"
        return "fail" if self.failures else "pass"

    @property
    def codes(self) -> set[str]:
        return {failure.code for failure in self.failures}

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "category": self.case.category,
            "expected_disposition": self.case.disposition,
            "observed_outcome": self.observation.outcome if self.observation else None,
            "status": self.status,
            "verified": self.integrity,
            "checks": self.checks,
            "failures": [failure.__dict__ for failure in self.failures],
            "citations": self.citations,
            "citation_blockers": self.citation_blockers,
            "entity_blockers": self.entity_blockers,
            "assertion_blockers": self.assertion_blockers,
            "reviewed": self.reviewed,
            "latency_ms": round(self.observation.latency_ms, 1) if self.observation else None,
        }


def _claim_payload(claim: Any) -> dict[str, Any] | None:
    if claim is None:
        return None
    return {
        "subject_id": claim.subject_id,
        "metric_id": claim.metric_id,
        "value": claim.value,
        "game_ids": list(claim.game_ids),
        "release_id": claim.release_id,
        "supporting_evidence_ids": list(claim.supporting_evidence_ids),
        "denominator": claim.denominator,
        "sample_size": claim.sample_size,
        # The claim's own attribution: arithmetic recomputes a whole-population recipe
        # only from the population and policy the claim says it used.
        "window": claim.window,
        "eligibility": dict(claim.eligibility or {}),
        "baseline_claim_ids": list(claim.baseline_claim_ids or ()),
    }


def _content_problem(
    reference: str,
    resolution: CitationResolution,
    mapping: RuntimeMapping,
    registry: dict[str, EvidenceRecord],
) -> str | None:
    """A resolved identity is not verified support until the registry content matches."""
    if resolution.unverified:
        # A recipe the record cannot prove blocks the measurement instead of crediting it.
        return "citation_content_unverified"
    if resolution.problems:
        # Missing committed evidence leaves the measurement blocked instead of failing it.
        return (
            "citation_content_unverified"
            if "calculation_evidence_missing" in resolution.problems
            else None
        )
    if resolution.kind == "calculation":
        return None
    record = registry.get(reference)
    if resolution.kind == "document":
        document = mapping.documents.get(reference)
        if document is None:
            return "citation_document_not_in_mapping"
        if record is None or record.payload_sha256 is None:
            return "citation_content_unverified"
        if record.payload_sha256 != document.payload_sha256:
            return "citation_content_mismatch"
        if record.payload is None:
            # A claimed digest is not content: without the payload it stays unverified.
            return "citation_content_unverified"
        if canonical_digest(record.payload) != record.payload_sha256:
            return "citation_content_mismatch"
        return None
    for canonical in resolution.canonical_ids:
        row = mapping.rows.get(canonical)
        if row is None:
            continue
        if record is None or record.row_sha256 is None:
            return "citation_content_unverified"
        if record.row_sha256 != row.row_sha256:
            return "citation_content_mismatch"
        if record.source_row is None:
            return "citation_content_unverified"
        if canonical_digest(record.source_row) != record.row_sha256:
            return "citation_content_mismatch"
    return None


def _citation_checks(
    case: ExpectationCase,
    observation: Observation,
    mapping: RuntimeMapping,
) -> tuple[list[AssertionFailure], list[dict[str, Any]], list[str]]:
    failures: list[AssertionFailure] = []
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    registry = observation.evidence
    by_claim: dict[str, set[str]] = {}
    # Only the reference's own content work is shared between claims. One claim's
    # verdict about a reference never stands in for another claim's.
    contents: dict[str, CalculationContent | None] = {}
    recorded: dict[str, dict[str, Any]] = {}
    seen_failures: set[tuple[str, str]] = set()

    def record(resolution: CitationResolution) -> None:
        row = recorded.get(resolution.reference)
        if row is None:
            row = {
                "reference": resolution.reference,
                "kind": resolution.kind,
                "resolved": resolution.resolved,
                "canonical_ids": list(resolution.canonical_ids),
                "recipe": resolution.recipe,
                "problems": list(resolution.problems),
                "unverified": list(resolution.unverified),
            }
            recorded[resolution.reference] = row
            rows.append(row)
        else:
            row["resolved"] = row["resolved"] and resolution.resolved
            row["canonical_ids"] = list(
                dict.fromkeys([*row["canonical_ids"], *resolution.canonical_ids])
            )
            row["problems"] = list(dict.fromkeys([*row["problems"], *resolution.problems]))
            row["unverified"] = list(dict.fromkeys([*row["unverified"], *resolution.unverified]))
            row["recipe"] = row["recipe"] or resolution.recipe
        for problem in resolution.problems:
            if (problem, resolution.reference) in seen_failures:
                continue
            seen_failures.add((problem, resolution.reference))
            failures.append(AssertionFailure(problem, resolution.reference))
        if resolution.unverified:
            blockers.append("citation_content_unverified")

    def verify(reference: str, payload: dict[str, Any] | None) -> CitationResolution:
        if reference not in contents:
            contents[reference] = mapping.calculation_content(reference, registry)
        resolution = mapping.resolve_citation(
            reference, payload, registry=registry, content=contents[reference]
        )
        record(resolution)
        problem = _content_problem(reference, resolution, mapping, registry)
        if problem:
            blockers.append(problem)
        return resolution

    seen_documents: set[str] = set()
    for citation in observation.citations:
        if not citation.possession_id:
            continue
        reference = f"{mapping.version}:{citation.possession_id}"
        if reference in seen_documents:
            continue
        seen_documents.add(reference)
        resolution = mapping.resolve_document(citation.possession_id)
        record(resolution)
        problem = _content_problem(reference, resolution, mapping, registry)
        if problem:
            blockers.append(problem)

    for claim in observation.claims:
        payload = _claim_payload(claim)
        if not claim.supporting_evidence_ids:
            failures.append(AssertionFailure("claim_without_receipt", claim.claim_id))
            blockers.append("citation_content_unverified")
            continue
        covered: set[str] = set()
        for reference in dict.fromkeys(claim.supporting_evidence_ids):
            covered.update(verify(reference, payload).canonical_ids)
        by_claim[claim.claim_id] = covered
    for citation in observation.citations:
        if not citation.evidence_id:
            continue
        verify(citation.evidence_id, _claim_payload(citation.claim))
    if not rows:
        failures.append(AssertionFailure("citation_missing_receipt", "no citation references"))
    return failures, rows, list(dict.fromkeys(blockers))


def _review_state(
    case: ExpectationCase, observation: Observation, decision: CaseDecision | None
) -> tuple[bool, list[AssertionFailure], list[str], bool]:
    """Validate a recorded review against the exact response it claims to have judged."""
    if decision is None:
        return False, [], [], True
    failures: list[AssertionFailure] = []
    blockers: list[str] = []
    answer = observation.answer.casefold()
    spans_ok = True
    for assertion in decision.assertions:
        if assertion.text.casefold() not in answer:
            spans_ok = False
            failures.append(AssertionFailure("review_unbound_assertion", assertion.text[:80]))
        if assertion.decision == "supported":
            continue
        if assertion.decision == "unsupported":
            failures.append(AssertionFailure("review_unsupported_assertion", assertion.text[:80]))
        else:
            blockers.append("assertion_evidence_unresolved")
    additions_ok = spans_ok and not any(
        assertion.decision == "unsupported" for assertion in decision.assertions
    )
    return spans_ok, failures, blockers, additions_ok


def score_case(
    case: ExpectationCase,
    observation: Observation | None,
    mapping: RuntimeMapping,
    decisions: DecisionRecord | None,
) -> CaseScore:
    result = CaseScore(case, observation)
    if observation is None:
        result.integrity = False
        result.failures.append(AssertionFailure("cases_missing", "no response recorded"))
        return result
    for problem in observation.problems:
        result.failures.append(AssertionFailure(problem.split(":", 1)[0], problem))
    if str(observation.request.get("question") or "") != case.question:
        result.failures.append(AssertionFailure("request_case_mismatch", observation.case_id))
    context_failure = _context_failure(case, observation)
    if context_failure is not None:
        result.failures.append(context_failure)
    if observation.outcome is None:
        result.failures.append(
            AssertionFailure(
                "outcome_missing_dependency" if observation.degraded else "outcome_missing",
                observation.route or "",
            )
        )
    elif observation.outcome != case.disposition:
        result.failures.append(
            AssertionFailure("disposition_mismatch", f"{observation.outcome} != {case.disposition}")
        )
    expected_request = observation.sent_request_id or observation.request_id
    for entry in observation.traces:
        for problem in entry.rank_problems():
            code, _, stage = problem.partition(":")
            result.failures.append(AssertionFailure(code, stage or entry.request_id))
        if entry.data_version != mapping.version:
            result.failures.append(AssertionFailure("trace_release_mismatch", entry.data_version))
        if expected_request and entry.request_id != expected_request:
            result.failures.append(AssertionFailure("trace_request_mismatch", entry.request_id))
    result.integrity = not (result.codes & INTEGRITY_CODES)

    decision = decisions.for_case(case.id, observation.response_sha256) if decisions else None
    reviewed, review_failures, assertion_blockers, additions_ok = _review_state(
        case, observation, decision
    )
    result.failures.extend(review_failures)
    result.assertion_blockers.extend(assertion_blockers)
    result.reviewed = reviewed
    result.checks["reviewed"] = reviewed
    result.checks["review_disposition_correct"] = (
        decision is not None
        and decision.disposition == case.disposition
        and decision.disposition == observation.outcome
    )
    result.checks["review_content_correct"] = (
        decision is not None
        and decision.paraphrase == "supported"
        and all(assertion.decision == "supported" for assertion in decision.assertions)
    )

    content_ok = True
    if case.disposition == "answer":
        if not case.facts:
            result.failures.append(AssertionFailure("no_expected_facts", case.id))
        tokens = numeric_tokens(observation.answer)
        checks: list[bool] = []
        for fact in case.facts:
            check = check_fact(fact, observation, mapping, tokens)
            result.failures.extend(check.failures)
            checks.append(check.passed)
        extra = extra_claims(case, observation, mapping)
        extras = unattributed_numbers(case, observation)
        entities = entity_assertions(case, observation, mapping)
        result.failures.extend(extra)
        result.failures.extend(extras)
        result.failures.extend(entities)
        citation_failures, citation_rows, citation_blockers = _citation_checks(
            case, observation, mapping
        )
        result.failures.extend(citation_failures)
        result.citations = citation_rows
        result.citation_blockers.extend(citation_blockers)
        result.entity_blockers.extend(
            ["entity_subject_unverifiable"] if "subject_unverifiable" in result.codes else []
        )
        codes = result.codes
        result.checks["facts"] = bool(checks) and all(checks) and not (codes & FACT_INVALID_CODES)
        result.checks["numeric"] = not (codes & (NUMERIC_CODES | FACT_INVALID_CODES))
        result.checks["entities"] = not (codes & (ENTITY_CODES | FACT_INVALID_CODES))
        result.checks["scope"] = not (codes & (SCOPE_CODES | FACT_INVALID_CODES))
        result.checks["no_additional_facts"] = not extra and additions_ok
        result.checks["numeric_attribution"] = not extras
        result.checks["citations"] = None if citation_blockers else not citation_failures
    elif case.disposition == "clarify":
        content_ok = not observation.claims
        if observation.claims:
            result.failures.append(
                AssertionFailure("clarification_with_claims", f"{len(observation.claims)} claims")
            )
    else:
        content_ok = not _dependency_failed(observation)
        if not content_ok:
            result.failures.append(
                AssertionFailure("refusal_dependency_failure", observation.analytics_status or "")
            )
    result.checks["disposition_content"] = content_ok
    if not result.integrity:
        for name in (
            "facts",
            "numeric",
            "entities",
            "scope",
            "no_additional_facts",
            "numeric_attribution",
            "citations",
            "disposition_content",
        ):
            result.checks[name] = False if name != "citations" else None
    return result


def _context_failure(case: ExpectationCase, observation: Observation) -> AssertionFailure | None:
    """The scored request must carry exactly the turns the question file declares."""
    raw = observation.request.get("context")
    if raw is None:
        return AssertionFailure(
            "request_context_missing",
            f"{case.id}: the recorded request carries no conversation context",
        )
    try:
        sent = conversation_context("the recorded request", raw)
    except LabelError as exc:
        return AssertionFailure("request_context_mismatch", f"{case.id}: {exc}")
    if sent != case.context:
        return AssertionFailure(
            "request_context_mismatch", f"{case.id}: {_context_difference(case.context, sent)}"
        )
    return None


def _context_difference(
    expected: tuple[dict[str, str], ...], sent: tuple[dict[str, str], ...]
) -> str:
    if len(expected) != len(sent):
        return f"{len(expected)} original turns but {len(sent)} turns were sent"
    for index, (want, got) in enumerate(zip(expected, sent, strict=True), start=1):
        if want != got:
            return (
                f"turn {index} differs: sent {got['role']} {got['content'][:60]!r}, "
                f"asked {want['role']} {want['content'][:60]!r}"
            )
    return "the sent turns are not the original ones"


def _dependency_failed(observation: Observation) -> bool:
    if observation.analytics_status == "dependency_failure":
        return True
    return any(entry.errors for entry in observation.traces)
