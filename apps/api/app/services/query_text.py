"""Text predicates shared by query resolution and follow-up scope inheritance.

Kept separate from the database-facing resolver so both the resolver and the typed
follow-up structure can name a metric, a record request or an explanation without a
circular import.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Literal

_METRICS = {
    "point": "points",
    "points": "points",
    "scoring": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "steal": "steals",
    "steals": "steals",
    "block": "blocks",
    "blocks": "blocks",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "plus minus": "plus_minus",
    "margin": "margin",
    "point differential": "margin",
    "scoring margin": "margin",
    "three": "three_pointers_made",
    "threes": "three_pointers_made",
}
_METRIC_PHRASE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in sorted(_METRICS, key=len, reverse=True)) + r")\b"
)
_EXPLANATION = re.compile(r"^\s*(?:why|explain)\b|\bexplain\b", re.I)
_AVERAGE_WORDS = re.compile(r"\b(?:average|averaged|averaging|avg|per game|ppg)\b", re.I)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def is_record_request(question: str) -> bool:
    """A record spans both outcomes; explicit subsets still take precedence."""
    q = normalize(question.replace("–", "-").replace("—", "-"))
    if re.search(r"\b(?:only|in)\s+(?:wins?|loss(?:es)?)\b", q):
        return False
    return bool(
        re.search(r"\brecord\b", q)
        or (re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q))
    )


METRIC_WORDS = frozenset(word for phrase in _METRICS for word in phrase.split())


def metrics_in_text(question: str) -> set[str]:
    """All named metrics. A longer phrase owns its overlapping words."""
    return {_METRICS[match[0]] for match in _METRIC_PHRASE.finditer(normalize(question))}


# Each period phrase and the periods it names. Scope checks reuse the same table, so a
# phrase the parser understands is never mistaken for an unknown subject.
_PERIOD_PHRASES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], set[int]]], ...] = (
    (re.compile(r"\bq([1-9])\b"), lambda m: {int(m.group(1))}),
    (re.compile(r"\b([1-9])(?:st|nd|rd|th) quarter\b"), lambda m: {int(m.group(1))}),
    (
        re.compile(r"\b(first|second|third|fourth) quarter\b"),
        lambda m: {("first", "second", "third", "fourth").index(m.group(1)) + 1},
    ),
    (re.compile(r"\bfirst half\b"), lambda m: {1, 2}),
    (re.compile(r"\bsecond half\b"), lambda m: {3, 4}),
    (re.compile(r"\blate (?:fourth|4th)\b"), lambda m: {4}),
)


def periods_in_text(question: str) -> list[int]:
    q = normalize(question)
    values: set[int] = set()
    for pattern, periods in _PERIOD_PHRASES:
        for match in pattern.finditer(q):
            values |= periods(match)
    return sorted(values)


def without_period_phrases(text: str) -> str:
    """Normalized text with every recognised period phrase removed."""
    q = normalize(text)
    for pattern, _ in _PERIOD_PHRASES:
        q = pattern.sub(" ", q)
    return q


def is_explanation(question: str) -> bool:
    return bool(_EXPLANATION.search(question))


def aggregations_in_text(question: str) -> set[Literal["average", "total"]]:
    values: set[Literal["average", "total"]] = set()
    if _AVERAGE_WORDS.search(question):
        values.add("average")
    if re.search(r"\btotal\b", question, re.I):
        values.add("total")
    return values
