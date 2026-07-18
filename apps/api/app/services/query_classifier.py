"""Query classification for analysis routing."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryClassifierResult:
    kind: str
    is_aggregative: bool
    confidence: float
    signals: list[str]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "is_aggregative": self.is_aggregative,
            "confidence": self.confidence,
            "signals": self.signals,
        }


_AGGREGATE_TERMS = (
    "average",
    "avg",
    "best",
    "biggest blowout",
    "biggest game",
    "biggest win",
    "total",
    "how many",
    "record",
    "win percentage",
    "wins",
    "losses",
    "losing streak",
    "longest",
    "most",
    "least",
    "rank",
    "per game",
    "streak",
    "wildest",
    "worst loss",
    "highest-scoring",
    "lowest-scoring",
    "at least",
    "points allowed",
    "home or away",
    "home and on the road",
    "perform",
    "stronger",
    "close games",
    "blowouts",
)
_COMPARATIVE_TERMS = ("compare", "versus", " vs ", "better", "worse", "more than", "less than")
_TEMPORAL_TERMS = ("before", "after", "since", "during", "last", "first", "quarter", "half")
_LINEUP_TERMS = ("lineup", "with ", "without ", "on court", "off court", "minutes together")
_COUNTERFACTUAL_TERMS = ("what if", "if they had", "would have", "could have", "hypothetical")


def classify_query(question: str) -> QueryClassifierResult:
    """Classify a user question into the RAG route dimensions.

    This is intentionally deterministic. LLM classification can be layered on
    later, but the query-time contract should not require network access.
    """
    q = f" {question.lower().strip()} "
    signals: list[str] = []

    comparative = any(term in q for term in _COMPARATIVE_TERMS) or bool(re.search(r"\bvs\.?\b", q))
    is_aggregative = any(term in q for term in _AGGREGATE_TERMS) or (
        comparative
        and not re.search(r"\bvs\.?\b", q)
        and not re.search(r"\bcompare\s+(?:that|this)\b", q)
    )
    if re.search(r"\bwhat did .+ do\b", q) or " explain " in q:
        is_aggregative = False
    if is_aggregative:
        signals.append("aggregate_terms")

    if any(term in q for term in _COUNTERFACTUAL_TERMS):
        signals.append("counterfactual_terms")
        return QueryClassifierResult("counterfactual", is_aggregative, 0.86, signals)

    if any(term in q for term in _LINEUP_TERMS):
        signals.append("lineup_terms")
        return QueryClassifierResult("lineup_conditioned", is_aggregative, 0.82, signals)

    if comparative:
        signals.append("comparative_terms")
        return QueryClassifierResult("comparative", is_aggregative, 0.78, signals)

    if any(term in q for term in _TEMPORAL_TERMS) or re.search(r"\bq[1-4]\b", q):
        signals.append("temporal_terms")
        return QueryClassifierResult("temporal", is_aggregative, 0.74, signals)

    if is_aggregative:
        return QueryClassifierResult("descriptive", True, 0.72, signals)

    return QueryClassifierResult("descriptive", False, 0.66, signals or ["default"])
