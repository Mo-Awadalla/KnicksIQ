"""Deterministic date and game-count window parsing for query resolution."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, NamedTuple

from app.services.query_text import normalize

if TYPE_CHECKING:
    from app.models.game import Game

_MONTHS = {
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
_MONTH_ALIASES = {
    **_MONTHS,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class DateWindow(NamedTuple):
    """Parsed window; ``explicit`` distinguishes a named window from inherited scope."""

    start: date | None
    end: date | None
    dates: list[date]
    explicit: bool
    single_day: bool
    named_month: int | None
    relative_count: int | None
    relative_from_start: bool


def _infer_year(month: int, day: int, games: list[Game], latest: date | None) -> int | None:
    years = sorted({game.game_date.year for game in games if game.game_date.month == month})
    if len(years) == 1:
        return years[0]
    if latest is None:
        return years[0] if years else None
    choices = years or [latest.year, latest.year - 1]
    valid = []
    for year in choices:
        try:
            date(year, month, day)
        except ValueError:
            continue
        valid.append(year)
    if not valid:
        return None
    return min(valid, key=lambda year: abs((date(year, month, day) - latest).days))


def _date_mentions(
    question: str, games: list[Game], latest: date | None
) -> list[tuple[int, int, date]]:
    """Every calendar day named in the question, in text order."""
    mentions: list[tuple[int, int, date]] = []
    for match in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", question):
        try:
            mentions.append((match.start(), match.end(), date.fromisoformat(match.group(0))))
        except ValueError:
            continue
    month_names = "|".join(sorted(_MONTH_ALIASES, key=len, reverse=True))
    patterns = (
        rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d{{2}}))?",
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\b(?:,?\s+(20\d{{2}}))?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, question, re.IGNORECASE):
            first, second = match.group(1), match.group(2)
            if first.isdigit():
                day, month = int(first), _MONTH_ALIASES[normalize(second)]
            else:
                month, day = _MONTH_ALIASES[normalize(first)], int(second)
            year_text = match.group(3)
            year = int(year_text) if year_text else _infer_year(month, day, games, latest)
            if year is None:
                continue
            try:
                value = date(year, month, day)
            except ValueError:
                continue
            if not any(start <= match.start() < end for start, end, _ in mentions):
                mentions.append((match.start(), match.end(), value))
    return sorted(mentions)


def _relative_window(q: str) -> tuple[int, bool] | None:
    """A relative count and whether it selects from the beginning of the scope."""
    count = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+games?\b", q)
    if count:
        return max(1, min(int(count.group(1)), 82)), False
    opening = re.search(r"\b(?:first|opening)\s+(\d+)\s+games?\b", q)
    if opening:
        return max(1, min(int(opening.group(1)), 82)), True
    if re.search(r"\b(?:last|previous)\s+game\b", q):
        return 1, False
    if re.search(r"\b(?:first|opening)\s+game\b", q):
        return 1, True
    return None


def date_window(question: str, games: list[Game], latest_date: date | None) -> DateWindow:
    """Parse explicit day/range and relative windows; callers apply bounds inclusively."""
    dates = sorted({game.game_date for game in games})
    first_game = dates[0] if dates else None
    q = normalize(question)
    mentions = _date_mentions(question, games, latest_date)
    relative = _relative_window(q)
    relative_count = relative[0] if relative else None
    relative_from_start = relative[1] if relative else False
    explicit = bool(mentions) or relative_count is not None

    def make(
        start: date | None,
        end: date | None,
        named_dates: list[date],
        is_explicit: bool,
        single_day: bool,
        named_month: int | None,
    ) -> DateWindow:
        return DateWindow(
            start,
            end,
            named_dates,
            is_explicit,
            single_day,
            named_month,
            relative_count,
            relative_from_start,
        )

    if mentions:
        first_start, first_end, first_value = mentions[0]
        if len(mentions) > 1:
            second_start, _, second_value = mentions[1]
            connector = question[first_end:second_start]
            if re.search(r"\b(?:and|to|through|thru|until)\b|[-–—]", connector, re.IGNORECASE):
                return make(first_value, second_value, [], True, False, None)
        prefix = question[max(0, first_start - 24) : first_start].lower()
        if re.search(r"\bsince\b", prefix):
            return make(first_value, latest_date, [], True, False, None)
        if re.search(r"\bafter\b", prefix):
            return make(first_value + timedelta(days=1), latest_date, [], True, False, None)
        if re.search(r"\bbefore\b", prefix):
            return make(first_game, first_value - timedelta(days=1), [], True, False, None)
        if re.search(r"\b(?:through|thru|until)\b", prefix):
            return make(first_game, first_value, [], True, False, None)
        if re.search(r"\bfrom\b", prefix):
            return make(first_value, latest_date, [], True, False, None)
        return make(first_value, first_value, [first_value], True, True, None)

    if latest_date and re.search(r"\bthis month\b", q):
        return make(latest_date.replace(day=1), latest_date, [], True, False, None)
    if latest_date and re.search(r"\blast month\b", q):
        previous_end = latest_date.replace(day=1) - timedelta(days=1)
        return make(previous_end.replace(day=1), previous_end, [], True, False, None)

    names = "|".join(sorted(_MONTH_ALIASES, key=len, reverse=True))
    month_match = re.search(rf"\b({names})\b(?:\s+(20\d{{2}}))?", q, re.IGNORECASE)
    if month_match:
        month = _MONTH_ALIASES[normalize(month_match.group(1))]
        year = int(month_match.group(2)) if month_match.group(2) else None
        # "may" and "march" are ordinary words; a month needs a date preposition or year.
        prefix = q[max(0, month_match.start() - 16) : month_match.start()]
        is_month_scope = (
            year is not None
            or re.search(
                r"\b(?:in|during|of|for|from|since|before|after|through|thru|until)\s+$",
                prefix,
            )
            or q.strip() == normalize(month_match.group(1))
        )
        if is_month_scope:
            if year is None:
                year = _infer_year(month, 1, games, latest_date)
            inside = [
                day for day in dates if day.month == month and (year is None or day.year == year)
            ]
            if inside:
                start, end = min(inside), max(inside)
            elif year is not None:
                start = date(year, month, 1)
                next_month = date(year + (month == 12), month % 12 + 1, 1)
                end = next_month - timedelta(days=1)
            else:
                start = end = None
            if start and end:
                if re.search(r"\bsince\b", prefix):
                    end = latest_date or end
                elif re.search(r"\bafter\b", prefix):
                    start, end = end + timedelta(days=1), latest_date or end
                elif re.search(r"\bbefore\b", prefix):
                    start, end = first_game, start - timedelta(days=1)
                elif re.search(r"\bfrom\b", prefix):
                    end = latest_date or end
                return make(start, end, [], True, False, month)
    return make(None, None, [], explicit, False, None)
