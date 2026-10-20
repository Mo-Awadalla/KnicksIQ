"""Per-game stat thresholds over STAT_REGISTRY stats ("more than 40 points")."""

from __future__ import annotations

import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from basketball_core.analytics.calculations import aggregate_rows
from basketball_core.analytics.registry import STAT_REGISTRY

Comparison = Literal["gt", "gte", "lt", "lte"]

_OPERATORS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}
SYMBOLS: dict[Comparison, str] = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_WORDING: dict[Comparison, str] = {
    "gt": "more than",
    "gte": "at least",
    "lt": "fewer than",
    "lte": "at most",
}
_PREFIXES: dict[str, Comparison] = {
    "no more than": "lte",
    "no fewer than": "gte",
    "no less than": "gte",
    "more than": "gt",
    "greater than": "gt",
    "over": "gt",
    "above": "gt",
    "at least": "gte",
    "fewer than": "lt",
    "less than": "lt",
    "under": "lt",
    "below": "lt",
    "at most": "lte",
}
_SUFFIXES: dict[str, Comparison] = {
    "plus": "gte",
    "or more": "gte",
    "or better": "gte",
    "or fewer": "lte",
    "or less": "lte",
}
_COUNTING_STATS = (
    "points",
    "rebounds",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "threes_made",
    "threes_attempted",
    "field_goals_made",
    "free_throws_made",
    "minutes",
)
# Game-level spellings the registry aliases do not cover.
_COLLOQUIAL = {
    "points": ("point",),
    "rebounds": ("rebound", "boards"),
    "assists": ("assist", "dimes"),
    "steals": ("steal",),
    "blocks": ("block", "blocked shots"),
    "turnovers": ("turnover",),
    "threes_made": (
        "three pointers",
        "three pointer",
        "3 pointers",
        "3 pointer",
        "threes",
        "triples",
        "3s",
    ),
    "threes_attempted": ("three pointers attempted", "3 pointers attempted"),
}
_STAT_WORDS = {
    re.sub(r"[-_]", " ", word.lower()): key
    for key in _COUNTING_STATS
    for word in (
        key,
        STAT_REGISTRY[key].label,
        *STAT_REGISTRY[key].aliases,
        *_COLLOQUIAL.get(key, ()),
    )
}
_STAT_PATTERN = "|".join(re.escape(word) for word in sorted(_STAT_WORDS, key=len, reverse=True))
_SCORING_VERB = re.compile(r"\bscor(?:e|es|ed|ing)\b")
_THRESHOLD = re.compile(
    r"(?:\b(?P<prefix>"
    + "|".join(re.escape(p) for p in sorted(_PREFIXES, key=len, reverse=True))
    + r")\s+)?(?<!per )(?<!last )(?<!first )\b(?P<value>\d+(?:\.\d+)?)"
    r"(?:\s*(?P<plus>\+)|\s+(?P<suffix>plus|or more|or better|or fewer|or less)\b)?"
    r"(?:\s+(?P<stat>" + _STAT_PATTERN + r")\b"
    r"(?:\s+(?P<trailing>or more|or better|or fewer|or less)\b)?)?"
)


@dataclass(frozen=True)
class StatThreshold:
    stat: str
    comparison: Comparison
    value: float

    @property
    def symbol(self) -> str:
        return SYMBOLS[self.comparison]

    @property
    def description(self) -> str:
        return (
            f"{_WORDING[self.comparison]} {self.value:g} {STAT_REGISTRY[self.stat].label.lower()}"
        )

    def observed(self, row: Mapping[str, Any] | Any) -> float | None:
        """One box-score row's value under the registry's aggregation convention."""
        return aggregate_rows([row], [self.stat])[self.stat]

    def meets(self, row: Mapping[str, Any] | Any) -> bool:
        observed = self.observed(row)
        return observed is not None and _OPERATORS[self.comparison](observed, self.value)


def parse_stat_threshold(text: str) -> StatThreshold | None:
    """Parse the first per-game stat threshold; a bare "N points" means at least N."""
    normalized = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", " ", text.lower())
    for match in _THRESHOLD.finditer(normalized):
        explicit = (
            _PREFIXES.get(match["prefix"] or "")
            or ("gte" if match["plus"] else None)
            or _SUFFIXES.get(match["suffix"] or match["trailing"] or "")
        )
        stat = _STAT_WORDS.get(match["stat"] or "")
        if stat is None and explicit and _SCORING_VERB.search(normalized, 0, match.start()):
            stat = "points"
        if stat is None:
            continue
        return StatThreshold(stat, explicit or "gte", float(match["value"]))
    return None
