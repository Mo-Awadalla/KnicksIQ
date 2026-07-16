"""Canonical NBA team aliases shared by analytics and retrieval."""

from __future__ import annotations

import re

TEAM_ALIASES = {
    "76ers": "PHI",
    "atlanta": "ATL",
    "hawks": "ATL",
    "boston": "BOS",
    "celtics": "BOS",
    "brooklyn": "BKN",
    "nets": "BKN",
    "bucks": "MIL",
    "charlotte": "CHA",
    "hornets": "CHA",
    "chicago": "CHI",
    "bulls": "CHI",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "cleveland": "CLE",
    "clippers": "LAC",
    "dallas": "DAL",
    "mavericks": "DAL",
    "denver": "DEN",
    "nuggets": "DEN",
    "detroit": "DET",
    "pistons": "DET",
    "golden state": "GSW",
    "warriors": "GSW",
    "houston": "HOU",
    "rockets": "HOU",
    "indiana": "IND",
    "pacers": "IND",
    "kings": "SAC",
    "lakers": "LAL",
    "magic": "ORL",
    "memphis": "MEM",
    "grizzlies": "MEM",
    "miami": "MIA",
    "heat": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "timberwolves": "MIN",
    "new orleans": "NOP",
    "pelicans": "NOP",
    "oklahoma city": "OKC",
    "thunder": "OKC",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "suns": "PHX",
    "portland": "POR",
    "trail blazers": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "spurs": "SAS",
    "sixers": "PHI",
    "toronto": "TOR",
    "raptors": "TOR",
    "utah": "UTA",
    "jazz": "UTA",
    "washington": "WAS",
    "wizards": "WAS",
}

_TEAM_IDS = frozenset({"NYK", *TEAM_ALIASES.values()})


def team_ids_in_text(text: str) -> set[str]:
    """Resolve exact team-name spans and canonical abbreviations from text."""
    lowered = text.lower()
    resolved = {
        team_id
        for alias, team_id in TEAM_ALIASES.items()
        if re.search(rf"\b{re.escape(alias)}\b", lowered)
    }
    resolved.update(
        token.upper()
        for token in re.findall(r"\b[a-z]{2,3}\b", lowered)
        if token.upper() in _TEAM_IDS
    )
    if re.search(r"\b(?:knicks|new york)\b", lowered):
        resolved.add("NYK")
    return resolved
