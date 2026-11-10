"""The deterministic scope a question names, and the games that scope admits.

Dates come from explicit ISO dates, named months, month/day endpoints or a named year,
periods from quarter and half wording, and the metric from the stat word the question
uses. Nothing here guesses: a part it cannot parse stays absent.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Literal

from app.models.game import Game
from app.services.query_comparison_specs import MONTH_NAMES
from app.services.query_operations import normalize_text

INTERVAL_WORDING = re.compile(r"\b(between|from|through|until)\b")

_METRICS = {
    "point": "points",
    "points": "points",
    "scoring": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "rebounding": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "assisting": "assists",
    "playmaking": "assists",
    "steal": "steals",
    "steals": "steals",
    "stealing": "steals",
    "block": "blocks",
    "blocks": "blocks",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "plus minus": "plus_minus",
    "three": "three_pointers_made",
    "threes": "three_pointers_made",
}

_MONTH_DAY = re.compile(
    r"\b(" + "|".join(_name for _name in MONTH_NAMES) + r")\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b"
)
_MONTH_YEAR = re.compile(
    r"\b(?:" + "|".join(_name for _name in MONTH_NAMES) + r")\s*,?\s+(20\d{2})\b"
)


def _periods(question: str) -> list[int]:
    q = normalize_text(question)
    values = {int(value) for value in re.findall(r"\bq([1-9])\b", q)}
    values.update(int(value) for value in re.findall(r"\b([1-9])(?:st|nd|rd|th) quarter\b", q))
    values.update(int(value) for value in re.findall(r"\bquarter\s+([1-9])\b", q))
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


def _month_day_dates(q: str, games: list[Game]) -> list[date]:
    """Resolve named month/day endpoints, honouring an explicitly named year.

    Without a year the endpoint falls in the calendar year the archive plays that month,
    so "March 1" belongs to this release's season. A named year is never replaced by the
    archive's year: an out-of-archive endpoint stays out and yields no games.
    """
    resolved: list[date] = []
    for name, day, year_text in _MONTH_DAY.findall(q):
        month = MONTH_NAMES[name]
        year = int(year_text) if year_text else None
        if year is None:
            year = next(
                (game.game_date.year for game in games if game.game_date.month == month), None
            )
        if year is None:
            continue
        try:
            resolved.append(date(year, month, int(day)))
        except ValueError:
            continue
    return resolved


def _named_year(q: str) -> int | None:
    """The calendar year written next to a named month, if the question names one."""
    match = _MONTH_YEAR.search(q)
    return int(match.group(1)) if match else None


def _month_interval(
    months: list[int],
    year: int | None,
    games: list[Game],
    q: str,
    latest_date: date | None,
) -> tuple[date | None, date | None]:
    """The calendar interval from the first named month through the last.

    The bounds are calendar bounds, not the archived games' first and last dates, so a
    month with no game keeps its place in the interval. "Since January" stays open-ended.
    """
    first, last = months[0], months[-1]
    start_year = year or next(
        (game.game_date.year for game in games if game.game_date.month == first), None
    )
    end_year = year or next(
        (game.game_date.year for game in games if game.game_date.month == last), None
    )
    if start_year is None or end_year is None:
        return None, None
    date_start = date(start_year, first, 1)
    if re.search(r"\bsince\b", q):
        return date_start, latest_date
    return date_start, date(end_year, last, calendar.monthrange(end_year, last)[1])


def _metric(question: str) -> str | None:
    q = normalize_text(question)
    return next(
        (
            metric
            for phrase, metric in sorted(_METRICS.items(), key=lambda item: -len(item[0]))
            if re.search(rf"\b{re.escape(phrase)}\b", q)
        ),
        None,
    )


def games_in_scope(
    games: list[Game],
    *,
    opponent_id: str | None,
    season_type: Literal["regular", "play_in", "playoffs"] | None,
    home_away: Literal["home", "away"] | None,
    date_start: date | None,
    date_end: date | None,
    game_result: Literal["W", "L"] | None,
    dates: tuple[date, ...] = (),
) -> list[Game]:
    """The games the resolved scope admits, in the archive's chronological order.

    `dates` holds the exact dates a question names; it stays empty when those dates bound
    an interval, because an interval is expressed through `date_start` and `date_end`.
    """
    candidates = games
    if opponent_id:
        candidates = [
            game for game in candidates if opponent_id in {game.home_team_id, game.away_team_id}
        ]
    if dates:
        candidates = [game for game in candidates if game.game_date in dates]
    if season_type:
        candidates = [game for game in candidates if game.season_type == season_type]
    if home_away == "home":
        candidates = [game for game in candidates if game.home_team_id == "NYK"]
    elif home_away == "away":
        candidates = [game for game in candidates if game.away_team_id == "NYK"]
    if date_start:
        candidates = [game for game in candidates if game.game_date >= date_start]
    if date_end:
        candidates = [game for game in candidates if game.game_date <= date_end]
    if game_result:
        candidates = [
            game
            for game in candidates
            if (
                (game.home_score if game.home_team_id == "NYK" else game.away_score)
                > (game.away_score if game.home_team_id == "NYK" else game.home_score)
            )
            == (game_result == "W")
        ]
    return candidates
