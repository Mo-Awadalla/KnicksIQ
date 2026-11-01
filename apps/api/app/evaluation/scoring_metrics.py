"""Metric construction and release gates for the evaluation report.

A metric is reported as ``blocked`` whenever its inputs are missing, never as a
passing value: fixed denominators stay fixed, unresolved semantic targets,
absent reviewer decisions and a provider stage each block explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.evaluation.observations import Submission
from app.evaluation.reviews import DecisionRecord
from app.evaluation.scoring_cases import CaseScore

PARAPHRASE_THRESHOLD = 0.95
CITATION_THRESHOLD = 0.95
SEMANTIC_THRESHOLD = 0.95
EXACT_THRESHOLD = 1.0


@dataclass
class Metric:
    name: str
    status: Literal["measured", "failed", "blocked"]
    denominator: int
    numerator: float = 0.0
    blockers: list[str] = field(default_factory=list)
    failing_cases: list[str] = field(default_factory=list)

    @property
    def value(self) -> float | None:
        if self.status == "blocked" or self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def as_dict(self) -> dict[str, Any]:
        # A semantic hit credits the share of its targets it ranked, so the numerator
        # may be fractional; a whole count still reports as a count.
        numerator = int(self.numerator) if float(self.numerator).is_integer() else self.numerator
        return {
            "status": self.status,
            "value": self.value,
            "numerator": numerator,
            "denominator": self.denominator,
            "blockers": list(self.blockers),
            "failing_cases": list(self.failing_cases),
        }


def _metric(name: str, denominator: int, blockers: list[str] | None = None) -> Metric:
    return Metric(
        name=name,
        status="blocked" if blockers else "measured",
        denominator=denominator,
        blockers=list(blockers or []),
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _observed(submission: Submission) -> dict[str, int]:
    counts = {"answer": 0, "clarify": 0, "refuse": 0, "unverified": 0}
    for item in submission.observations:
        if item.outcome in counts:
            counts[item.outcome] += 1
        else:
            counts["unverified"] += 1
    return counts


def _disposition_credited(item: CaseScore) -> bool:
    return (
        item.observation is not None
        and item.integrity
        and item.reviewed
        and item.observation.outcome == item.case.disposition
        and item.checks.get("disposition_content") is True
        and item.checks.get("review_disposition_correct") is True
        and item.checks.get("review_content_correct") is True
    )


def _behavior_credited(item: CaseScore) -> bool:
    if not _disposition_credited(item):
        return False
    return item.case.disposition != "answer" or all(
        item.checks.get(name) is True
        for name in (
            "facts",
            "numeric",
            "entities",
            "scope",
            "no_additional_facts",
            "numeric_attribution",
            "citations",
        )
    )


def disposition_metrics(scores: list[CaseScore], review_blockers: list[str]) -> list[Metric]:
    """Disposition accuracy plus clarification, refusal and combined abstention.

    A case credits only when its response verified, its disposition content matched
    the case type and a recorded review judged that same response.
    """
    clarify_scores = [item for item in scores if item.case.disposition == "clarify"]
    refuse_scores = [item for item in scores if item.case.disposition == "refuse"]
    abstention_scores = clarify_scores + refuse_scores

    def measured(name: str, group: list[CaseScore]) -> Metric:
        value = _metric(name, len(group), review_blockers)
        value.numerator = sum(1 for item in group if _disposition_credited(item))
        value.failing_cases = [item.case.id for item in group if not _disposition_credited(item)]
        return value

    disposition = measured("disposition_accuracy", scores)
    abstention = measured("correct_abstention", abstention_scores)
    clarification = measured("clarification_accuracy", clarify_scores)
    refusal = measured("refusal_accuracy", refuse_scores)
    return [disposition, abstention, clarification, refusal]


def _blockers(scores: list[CaseScore], attribute: str) -> list[str]:
    merged: list[str] = []
    for item in scores:
        for blocker in getattr(item, attribute):
            if blocker not in merged:
                merged.append(blocker)
    return merged


def answer_metrics(answer_scores: list[CaseScore]) -> list[Metric]:
    """Numeric, entity, scope, addition and citation correctness over answer cases."""
    entity_blockers = _blockers(answer_scores, "entity_blockers")
    assertion_blockers = _blockers(answer_scores, "assertion_blockers")
    citation_blockers = _blockers(answer_scores, "citation_blockers")

    def measured(name: str, check: str, blockers: list[str] | None = None) -> Metric:
        metric = _metric(name, len(answer_scores), (blockers or None))
        metric.numerator = sum(
            1 for item in answer_scores if item.integrity and item.checks.get(check) is True
        )
        metric.failing_cases = [
            item.case.id
            for item in answer_scores
            if not item.integrity or item.checks.get(check) is not True
        ]
        return metric

    additions = measured(
        "unsupported_additional_fact_rate", "no_additional_facts", assertion_blockers
    )
    additions.numerator = sum(
        1
        for item in answer_scores
        if item.integrity
        and item.checks.get("no_additional_facts") is True
        and item.checks.get("numeric_attribution") is True
    )
    additions.failing_cases = [
        item.case.id
        for item in answer_scores
        if not item.integrity
        or item.checks.get("no_additional_facts") is not True
        or item.checks.get("numeric_attribution") is not True
    ]
    return [
        measured("canonical_numeric_correctness", "numeric"),
        measured("canonical_entity_correctness", "entities", entity_blockers),
        measured("scope_window_denominator_correctness", "scope"),
        additions,
        measured("citation_receipt_correctness", "citations", citation_blockers),
    ]


def semantic_metrics(semantic_cases: list[CaseScore], review_blockers: list[str]) -> list[Metric]:
    """Judge the unchanged original semantic cohort by its expected behavior."""
    behavior = _metric("legacy_semantic_behavior_accuracy", len(semantic_cases), review_blockers)
    behavior.numerator = sum(1 for item in semantic_cases if _behavior_credited(item))
    behavior.failing_cases = [
        item.case.id for item in semantic_cases if not _behavior_credited(item)
    ]
    missing = ["narrative_benchmark_missing"]
    return [
        behavior,
        _metric("narrative_recall_at_5", 0, missing),
        _metric("narrative_recall_at_20", 0, missing),
    ]


def review_metrics(
    answer_scores: list[CaseScore],
    decisions: DecisionRecord | None,
    review_blockers: list[str],
) -> list[Metric]:
    """Paraphrase and answer quality are measured only from recorded decisions."""
    paraphrase = _metric("paraphrase_quality", len(answer_scores), review_blockers)
    quality = _metric("answer_quality", len(answer_scores), review_blockers)
    if decisions is not None and not review_blockers:
        paraphrase.numerator = sum(
            1
            for item in answer_scores
            if item.integrity and decisions.cases[item.case.id].paraphrase == "supported"
        )
        quality.numerator = sum(1 for item in answer_scores if _behavior_credited(item))
        paraphrase.failing_cases = [
            item.case.id
            for item in answer_scores
            if not item.integrity or decisions.cases[item.case.id].paraphrase != "supported"
        ]
        quality.failing_cases = [
            item.case.id for item in answer_scores if not _behavior_credited(item)
        ]
    return [paraphrase, quality]


def latency_entries(submission: Submission) -> dict[str, dict[str, Any]]:
    """Latency percentiles and the observed provider-request count."""
    latencies = [item.latency_ms for item in submission.observations]
    return {
        "latency_p50_ms": {
            "status": "measured" if latencies else "blocked",
            "value": _percentile(latencies, 0.50),
            "numerator": 0,
            "denominator": len(latencies),
            "blockers": [] if latencies else ["no responses"],
            "failing_cases": [],
        },
        "latency_p95_ms": {
            "status": "measured" if latencies else "blocked",
            "value": _percentile(latencies, 0.95),
            "numerator": 0,
            "denominator": len(latencies),
            "blockers": [] if latencies else ["no responses"],
            "failing_cases": [],
        },
        "provider_requests": {
            "status": "measured",
            "value": submission.provider_requests,
            "numerator": submission.provider_requests,
            "denominator": 0,
            "blockers": [],
            "failing_cases": [],
        },
    }


GATE_THRESHOLDS = {
    "disposition_accuracy": EXACT_THRESHOLD,
    "correct_abstention": EXACT_THRESHOLD,
    "canonical_numeric_correctness": EXACT_THRESHOLD,
    "canonical_entity_correctness": EXACT_THRESHOLD,
    "scope_window_denominator_correctness": EXACT_THRESHOLD,
    "unsupported_additional_fact_rate": EXACT_THRESHOLD,
    "citation_receipt_correctness": CITATION_THRESHOLD,
    "legacy_semantic_behavior_accuracy": EXACT_THRESHOLD,
    "narrative_recall_at_5": SEMANTIC_THRESHOLD,
    "paraphrase_quality": PARAPHRASE_THRESHOLD,
}


def _gates(metrics: dict[str, dict[str, Any]], blockers: list[dict[str, str]]) -> dict[str, Any]:
    global_blockers = [
        item["code"]
        for item in blockers
        if item["code"]
        in {
            "labels_owner_unapproved",
            "labels_not_frozen",
            "labels_digest_unverified",
            "cases_missing",
            "duplicate_observation",
            "unknown_case_observation",
            "provider_requests_observed",
            "assertion_evidence_unresolved",
            "citation_content_unverified",
            "entity_subject_unverifiable",
            "labels_freeze_unverified",
            "labels_approval_unverified",
        }
        or item["code"].startswith("narrative_")
    ]
    gates: dict[str, Any] = {}
    for name, threshold in GATE_THRESHOLDS.items():
        entry = metrics[name]
        blocked_by = list(entry["blockers"]) + global_blockers
        if entry["status"] == "blocked":
            status = "blocked"
        elif entry["value"] is not None and entry["value"] >= threshold:
            status = "blocked" if global_blockers else "pass"
        else:
            status = "fail"
        gates[name] = {
            "threshold": threshold,
            "status": status,
            "value": entry["value"],
            "blocked_by": blocked_by,
        }
    return gates
