"""Season-phase policy for the held-out analyst evaluation set.

The phase is resolved from the question text with an ordered rule table. This module never
sees a response. See the policy table in
docs/release-evidence/llm-primary-20261021/final/relabel/README.md.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from app.evaluation.heldout_facts import Archive

Phase = Literal["regular", "playoffs", "play_in", "all", "both", "window", "game"]

_ISO_DATE = r"\b20\d{2}-\d{2}-\d{2}\b"
_MONTH_DAY = (
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|"
    r"december)\s+\d{1,2}\b"
)
_MONTH_WINDOW = (
    r"\b(?:in|during|for|over)\s+(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b"
)
_GAME = r"\bgame\s+[1-7]\b"
_ALL_PHASES = r"\boverall\b|\bincluding playoffs\b|\ball phases\b"
_PLAYOFFS = r"\bplayoffs?\b|\bpostseason\b"
_PLAY_IN = r"\bplay-in\b|\bplay in (?:the )?(?:tournament|game|round|matchup)\b"
_REGULAR = r"\bregular[ -]season\b"
_RELATIVE = r"\b(?:last|first|final|previous)\s+\d+\s+(?:games?|appearances?)\b"

# Non-Knicks team vocabulary. An opponent question spans every phase.
_OPPONENTS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bheat\b|\bmiami\b",
        r"\bcavaliers?\b|\bcavs\b|\bcleveland\b",
        r"\bsixers?\b|\b76ers\b|\bphiladelphia\b|\bphi\b",
        r"\bspurs?\b|\bsan antonio\b|\bsas\b",
        r"\bthunder\b|\boklahoma city\b|\bokc\b",
        r"\bpistons?\b|\bdetroit\b",
        r"\blakers?\b|\blal\b",
        r"\bbucks?\b|\bmilwaukee\b",
        r"\bnuggets?\b|\bdenver\b",
        r"\braptors?\b|\btoronto\b",
        r"\bceltics?\b|\bboston\b",
        r"\bnets\b|\bbrooklyn\b",
        r"\bhawks\b|\batlanta\b",
        r"\bhornets\b|\bcharlotte\b",
        r"\bbulls\b|\bchicago\b",
        r"\bpacers\b|\bindiana\b",
        r"\bwizards\b|\bwashington\b",
        r"\bmagic\b|\borlando\b",
        r"\bmavericks?\b|\bdallas\b",
        r"\brockets?\b|\bhouston\b",
        r"\bgrizzlies\b|\bmemphis\b",
        r"\bpelicans\b|\bnew orleans\b",
        r"\btimberwolves\b|\bminnesota\b",
        r"\btrail blazers\b|\bportland\b",
        r"\bkings\b|\bsacramento\b",
        r"\bclippers\b",
        r"\bwarriors\b|\bgolden state\b",
        r"\bsuns\b|\bphoenix\b",
        r"\bjazz\b|\butah\b",
    )
)


def phase_policy(question: str) -> tuple[Phase, str]:
    """Resolve the phase and the rule that matched. The question text is the only input."""
    q = question.casefold()
    if re.search(_GAME, q) or re.search(_MONTH_DAY, q):
        return "game", "specific_game"
    if re.search(_ISO_DATE, q):
        if re.search(r"\b(between|from|through|until|since|before)\b", q):
            return "window", "date_window"
        return "game", "specific_game"
    if re.search(_ALL_PHASES, q):
        return "all", "all_phases_phrase"
    named = {
        phase
        for phase, pattern in (
            ("playoffs", _PLAYOFFS),
            ("play_in", _PLAY_IN),
            ("regular", _REGULAR),
        )
        if re.search(pattern, q)
    }
    if len(named) > 1:
        return "both", "both_named_phases"
    if named:
        phase = named.pop()
        return phase, f"{phase}_named"  # type: ignore[return-value]
    if any(pattern.search(q) for pattern in _OPPONENTS):
        return "all", "opponent"
    if re.search(_MONTH_WINDOW, q):
        return "window", "date_window"
    if re.search(_RELATIVE, q):
        return "all", "relative_window"
    return "regular", "season_level_default"


def resolved_phase(question: str) -> Phase:
    """Resolve the phase from the question text only. See the policy table in the evidence."""
    return phase_policy(question)[0]


def season_type_for(phase: Phase) -> str | None:
    """The season filter for a phase. Window and game builders select their own games."""
    return phase if phase in ("regular", "playoffs", "play_in") else None


def phase_games(
    archive: Archive,
    phase: Phase,
    *,
    opponent: str | None = None,
    start: date | None = None,
    end: date | None = None,
    site: str | None = None,
) -> list:
    return archive.select(
        season_type=season_type_for(phase),
        opponent=opponent,
        start=start,
        end=end,
        site=site,
    )
