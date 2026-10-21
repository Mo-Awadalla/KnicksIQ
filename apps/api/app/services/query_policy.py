"""Season-phase and outcome-population rules shared by query resolution and calculations."""

from __future__ import annotations

import re

from app.services.query_resolution import _normalize

_PHASE_WORDS = re.compile(r"\b(?:playoff|postseason|play in|regular season|overall|all phases)\b")
_OUTCOME_SUBSET = re.compile(
    r"\b(?:only|just)\s+(?:wins?|loss(?:es)?)\b"
    r"|\b(?:in|during|within)\s+(?:[a-z]+\s+){0,3}(?:wins?|loss(?:es)?)\b"
    r"|\b(?:won|lost)\s+games?\b"
    r"|\bwhen\s+(?:they|the\s+knicks|nyk)\s+(?:win|lose)\b"
)


def season_type_label(season_type: str | None) -> str:
    return {
        "regular": "regular season",
        "playoffs": "playoffs",
        "play_in": "play-in",
    }.get(season_type or "", "all phases")


def names_phase(question: str) -> bool:
    return bool(_PHASE_WORDS.search(_normalize(question)))


def is_outcome_subset(question: str) -> bool:
    """True when wins or losses name the population, not the thing being counted.

    "How many road games did they win" counts wins inside the full road population;
    "their stats in wins" restricts the population to wins. Only the latter may filter.
    """
    return bool(_OUTCOME_SUBSET.search(_normalize(question)))
