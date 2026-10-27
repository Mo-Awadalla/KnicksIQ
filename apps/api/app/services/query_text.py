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
    "scorer": "points",
    "scorers": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "rebounding": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "assisting": "assists",
    "double double": "double_doubles",
    "double doubles": "double_doubles",
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
    "three point percentage": "three_point_percentage",
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
    if re.search(r"\b(?:only|in)\s+(?:(?:home|road|away)\s+)?(?:wins?|loss(?:es)?)\b", q):
        return False
    all_games_outcome = bool(
        re.search(r"\b(?:all|each)\s+(?:of\s+)?(?:those|these|the)\s+games\b", q)
        and re.search(r"\b(?:win|wins|won|lose|loses|lost|losses)\b", q)
    )
    return bool(
        re.search(r"\brecord\b", q)
        or all_games_outcome
        or (re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q))
        or (
            re.search(r"^how (?:did|have|has)\b.*\b(?:perform|do|done|fare)\b", q)
            and not metrics_in_text(question)
            and not re.search(r"\b(?:scores?|margin|rating|run)\b", q)
        )
    )


def is_game_score_request(question: str) -> bool:
    """Detect a single game's score, not per-game player rates."""
    q = normalize(question)
    return bool(
        not re.search(r"\bper\s+game\b", q)
        and re.search(r"\b(?:the|final) score\b|\bscore (?:against|on|of)\b", q)
    )


METRIC_WORDS = frozenset(word for phrase in _METRICS for word in phrase.split())


def metrics_in_text(question: str) -> set[str]:
    """All named metrics. A longer phrase owns its overlapping words."""
    normalized = normalize(question)
    if re.search(r"\b(?:games?|times)\b.*\bstart(?:ed)?\b", normalized):
        return {"starts"}
    return {_METRICS[match[0]] for match in _METRIC_PHRASE.finditer(normalized)}


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
    if _AVERAGE_WORDS.search(question) or re.search(r"\bper[ -]appearance\b", question, re.I):
        values.add("average")
    if re.search(r"\b(?:total|sum)\b", question, re.I):
        values.add("total")
    return values
