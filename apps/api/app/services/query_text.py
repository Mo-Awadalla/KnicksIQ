"""Text predicates shared by query resolution and follow-up scope inheritance.

Kept separate from the database-facing resolver so both the resolver and the typed
follow-up structure can name a metric, a record request or an explanation without a
circular import.
"""

from __future__ import annotations

import re
import unicodedata
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


def metric_in_text(question: str) -> str | None:
    q = normalize(question)
    return next(
        (
            metric
            for phrase, metric in sorted(_METRICS.items(), key=lambda item: -len(item[0]))
            if re.search(rf"\b{re.escape(phrase)}\b", q)
        ),
        None,
    )


def periods_in_text(question: str) -> list[int]:
    q = normalize(question)
    values = {int(value) for value in re.findall(r"\bq([1-9])\b", q)}
    values.update(int(value) for value in re.findall(r"\b([1-9])(?:st|nd|rd|th) quarter\b", q))
    for period, ordinal in enumerate(("first", "second", "third", "fourth"), start=1):
        if re.search(rf"\b{ordinal} quarter\b", q):
            values.add(period)
    if "first half" in q:
        values.update({1, 2})
    if "second half" in q:
        values.update({3, 4})
    if "late fourth" in q or "late 4th" in q:
        values.add(4)
    return sorted(values)


def is_explanation(question: str) -> bool:
    return bool(_EXPLANATION.search(question))


def aggregation_of(question: str) -> Literal["average", "total"] | None:
    if _AVERAGE_WORDS.search(question):
        return "average"
    if re.search(r"\btotal\b", question, re.I):
        return "total"
    return None
