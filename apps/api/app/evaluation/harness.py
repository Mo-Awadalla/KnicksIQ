"""Actionable metrics for a human-labelled analyst evaluation set."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?%?")
_SPACE = re.compile(r"\s+")


def _normalise(value: object) -> str:
    return _SPACE.sub(" ", str(value).casefold()).strip()


def _numbers(value: object) -> set[str]:
    return set(_NUMBER.findall(str(value).replace(",", "")))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: str
    question: str
    expected_route: str | None
    relevant_evidence_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    answerable: bool
    filters: dict[str, Any]
    context: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluationCase:
        return cls(
            id=str(value["id"]),
            category=str(value["category"]),
            question=str(value["question"]),
            expected_route=value.get("expected_route"),
            relevant_evidence_ids=tuple(value.get("relevant_evidence_ids", [])),
            required_facts=tuple(str(item) for item in value.get("required_facts", [])),
            answerable=bool(value["answerable"]),
            filters=dict(value.get("filters", {})),
            context=tuple(value.get("context", [])),
        )


@dataclass(frozen=True)
class QueryObservation:
    case: EvaluationCase
    response: dict[str, Any]
    latency_ms: float


@dataclass
class EvaluationReport:
    metrics: dict[str, float | int | None]
    reranker_diagnosis: dict[str, int]
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "reranker_diagnosis": self.reranker_diagnosis,
            "failures": self.failures,
        }


def _retrieval_ids(response: dict[str, Any], key: str) -> list[str]:
    ids: list[str] = []
    for call in response.get("tool_calls", []):
        ids.extend(str(item) for item in call.get(key, []))
    return list(dict.fromkeys(ids))


def _citation_ids(response: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for citation in response.get("citations", []):
        metadata = citation.get("metadata", {})
        if citation.get("game_id") is not None:
            result.add(f"game:{citation['game_id']}")
        if metadata.get("possession_id"):
            result.add(f"possession:{metadata['possession_id']}")
        if metadata.get("evidence_id"):
            result.add(str(metadata["evidence_id"]))
    return result


def _recall(relevant: set[str], retrieved: Iterable[str]) -> float | None:
    if not relevant:
        return None
    return len(relevant & set(retrieved)) / len(relevant)


def evaluate(observations: Iterable[QueryObservation]) -> EvaluationReport:
    rows = list(observations)
    if not rows:
        raise ValueError("at least one observation is required")
    route_hits: list[bool] = []
    recall5: list[float] = []
    recall20: list[float] = []
    numeric_hits: list[bool] = []
    citation_hits: list[bool] = []
    completeness: list[float] = []
    abstention_hits: list[bool] = []
    latencies: list[float] = []
    llm_calls = 0
    total_cost = 0.0
    diagnosis = {"reranking_may_help": 0, "retrieval_miss": 0, "already_top5": 0}
    failures: list[dict[str, Any]] = []

    for row in rows:
        case, response = row.case, row.response
        answer = str(response.get("answer", ""))
        relevant = set(case.relevant_evidence_ids)
        top5 = _retrieval_ids(response, "returned_evidence_ids")[:5]
        top20 = _retrieval_ids(response, "candidate_evidence_ids")[:20]
        if not top5:
            top5 = list(_citation_ids(response))[:5]
        if not top20:
            top20 = top5

        route_ok = response.get("route") == case.expected_route
        route_hits.append(route_ok)
        r5, r20 = _recall(relevant, top5), _recall(relevant, top20)
        if r5 is not None:
            recall5.append(r5)
            recall20.append(r20 or 0.0)
            if r5 < 1 and (r20 or 0) > r5:
                diagnosis["reranking_may_help"] += 1
            elif (r20 or 0) == 0:
                diagnosis["retrieval_miss"] += 1
            else:
                diagnosis["already_top5"] += 1

        required_numbers = _numbers(" ".join(case.required_facts))
        numeric_ok = required_numbers.issubset(_numbers(answer))
        if required_numbers:
            numeric_hits.append(numeric_ok)
        fact_hits = [
            _normalise(fact) in _normalise(answer) or _numbers(fact).issubset(_numbers(answer))
            for fact in case.required_facts
        ]
        completeness.append(sum(fact_hits) / len(fact_hits) if fact_hits else 1.0)
        cited = _citation_ids(response)
        citation_ok = not relevant or bool(relevant & cited)
        if case.answerable and relevant:
            citation_hits.append(citation_ok)
        abstention_ok = bool(response.get("refused")) if not case.answerable else True
        if not case.answerable:
            abstention_hits.append(abstention_ok)

        calls = response.get("tool_calls", [])
        llm_calls += sum(
            call.get("tool") in {"llm_generate", "llm_planner", "retrieval_plan"} for call in calls
        )
        total_cost += sum(
            float(call.get("cost_usd", call.get("estimated_cost_usd", 0)) or 0) for call in calls
        )
        latencies.append(row.latency_ms)
        reasons = [
            name
            for name, passed in (
                ("route", route_ok),
                ("numeric", numeric_ok),
                ("citations", citation_ok),
                ("abstention", abstention_ok),
                ("completeness", all(fact_hits)),
            )
            if not passed
        ]
        if reasons:
            failures.append({"id": case.id, "failed": reasons})

    count = len(rows)
    return EvaluationReport(
        metrics={
            "query_count": count,
            "routing_accuracy": statistics.fmean(route_hits),
            "relevant_evidence_recall_at_5": statistics.fmean(recall5) if recall5 else None,
            "relevant_evidence_recall_at_20": statistics.fmean(recall20) if recall20 else None,
            "exact_numeric_correctness": statistics.fmean(numeric_hits) if numeric_hits else None,
            "citation_correctness": statistics.fmean(citation_hits) if citation_hits else None,
            "answer_completeness": statistics.fmean(completeness),
            "correct_abstention_rate": (
                statistics.fmean(abstention_hits) if abstention_hits else None
            ),
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "llm_calls_per_query": llm_calls / count,
            "cost_usd_per_query": total_cost / count,
        },
        reranker_diagnosis=diagnosis,
        failures=failures,
    )
