"""Season-phase and outcome-population rules shared by query resolution and calculations."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, NamedTuple

SeasonType = Literal["regular", "play_in", "playoffs"]


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


_PHASE_WORDS = re.compile(r"\b(?:playoffs?|postseason|regular season|overall|all phases)\b")
# Normalization turns "play-in" into "play in", which also reads "how did they play in November".
_PLAY_IN = re.compile(r"\bthe play in\b|\bplay in (?:game|games|tournament|round)\b")
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


def names_play_in(question: str) -> bool:
    return "play-in" in question.lower() or bool(_PLAY_IN.search(_normalize(question)))


def names_phase(question: str) -> bool:
    return names_play_in(question) or bool(_PHASE_WORDS.search(_normalize(question)))


def names_all_phases(question: str) -> bool:
    q = _normalize(question)
    return bool(re.search(r"\boverall\b|\bincluding (?:the )?playoffs\b|\ball phases\b", q))


class Phase(NamedTuple):
    named: bool
    season_type: SeasonType | None
    # True only when every phase was asked for (or inherited), never when merely unspecified.
    all_phases: bool


def resolve_phase(
    question: str,
    *,
    season_level: bool,
    default: SeasonType | None = "regular",
    default_all_phases: bool = False,
) -> Phase:
    """The phase a question is scoped to.

    Season-level stats use ``default``: the regular season, or in a follow-up the phase
    under discussion. ``default_all_phases`` marks that phase as every phase; without it
    a ``None`` default is an unspecified phase (a matchup or window spans every phase
    but did not ask for every phase). Matchups and windows span every phase.
    """
    q = _normalize(question)
    play_in = names_play_in(question)
    named = play_in or bool(re.search(r"\bplayoff|\bpostseason|\bregular season\b", q))
    season_type: SeasonType | None = (
        "playoffs"
        if "playoff" in q or "postseason" in q
        else "play_in"
        if play_in
        else "regular"
        if "regular season" in q
        else None
    )
    if names_all_phases(question):
        return Phase(named=named, season_type=None, all_phases=True)
    if season_type is None and season_level:
        return Phase(named=named, season_type=default, all_phases=default_all_phases)
    return Phase(named=named, season_type=season_type, all_phases=False)


def is_outcome_subset(question: str) -> bool:
    """True when wins or losses name the population, not the thing being counted.

    "How many road games did they win" counts wins inside the full road population;
    "their stats in wins" restricts the population to wins. Only the latter may filter.
    """
    return bool(_OUTCOME_SUBSET.search(_normalize(question)))
