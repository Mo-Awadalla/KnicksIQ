"""Requested source types: what the model sees of a receipt and whether an answer cites one."""

from __future__ import annotations

import re
from typing import Any

from app.services.evidence_contracts import Evidence, ProposedAnswer

SOURCE_LABELS = {
    "possessions": "play_by_play",
    "reports": "game_report",
    "games": "game_record",
    "box_scores": "box_score",
}
CITATION_TITLES = {
    "possessions": "Play-by-play receipt",
    "reports": "Game report",
    "games": "Game record",
    "box_scores": "Box score",
}
_REQUESTS = (
    ("possessions", re.compile(r"\bplay[- ]?by[- ]?play\b|\bpossessions?\b", re.IGNORECASE)),
    ("reports", re.compile(r"\b(?:game |written )?reports?\b|\brecaps?\b", re.IGNORECASE)),
)


def collection(item: Evidence) -> str | None:
    return item.metadata.get("document_collection")


def requested_sources(question: str) -> frozenset[str]:
    """Source collections the question explicitly asks to see; any one of them satisfies it."""
    return frozenset(name for name, pattern in _REQUESTS if pattern.search(question))


def evidence_view(item: Evidence) -> dict[str, Any]:
    """The receipt as the model sees it.

    Retrieved receipts carried their whole index payload (lineups, semantic summary, fusion
    ranks), about 2 KB each, so none fit beside the claims and the writer could not cite the
    play-by-play it was asked for. The text already states date, period, clock and score;
    provenance stays in the server registry and citations are rendered from it.
    """
    view: dict[str, Any] = {"evidence_id": item.evidence_id, "text": item.text}
    source = SOURCE_LABELS.get(collection(item) or "")
    if source:
        view["source_type"] = source
    if item.game_id is not None:
        view["game_id"] = item.game_id
    return view


def scope_view(scope: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in scope.items() if value not in (None, [], {}, (), False)}


def priority(question: str, evidence: list[Evidence]) -> list[Evidence]:
    """Highest-ranked receipt of each requested source type, in retrieval order."""
    wanted = requested_sources(question)
    first: dict[str, Evidence] = {}
    for item in evidence:
        source = collection(item)
        if source in wanted and source not in first:
            first[source] = item
    return list(first.values())


def citation_gap(question: str, answer: ProposedAnswer, sent: dict[str, Evidence]) -> str | None:
    """Repair reason when the writer saw a requested source type but cited none of it."""
    wanted = requested_sources(question)
    available = {ref for ref, item in sent.items() if collection(item) in wanted}
    if not available or available.intersection(answer.evidence_ids):
        return None
    names = " or ".join(sorted(SOURCE_LABELS[name] for name in wanted))
    return (
        f"The question asks for a {names} receipt and one was provided. Cite at least one "
        "evidence_id whose source_type matches, and describe each receipt only as its "
        "source_type."
    )
