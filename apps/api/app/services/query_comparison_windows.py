"""The windows and stated counts a comparison question names.

A window is the first or last N of one unit, so this module both reads it from the text
and takes it over rows whose unit is already decided. A stated game count the archive
contradicts is a question, not a scope.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.query_comparison_specs import ComparisonResolution, WindowSpec
from app.services.query_operations import normalize_text

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_WINDOW_QUALIFIER = (
    r"(?:regular season|postseason|post season|playoff|playoffs|home|road|away|"
    r"conference|archived|knicks)\s+"
)
WINDOW_ASK = re.compile(
    r"\b(?P<position>first|last|final|previous)\s+(?P<count>\d{1,2})\s+"
    r"(?:" + _WINDOW_QUALIFIER + r"){0,2}games?\b"
)
_COUNT_PREMISE = re.compile(
    r"\b(?:the\s+)?(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(?:knicks\s+|archived\s+)?games?\b"
)


def single_window(normalized: str) -> WindowSpec | None:
    """The one first/last N window a question names, if it names exactly one."""
    matches = list(WINDOW_ASK.finditer(normalized))
    if len(matches) != 1:
        return None
    match = matches[0]
    count = int(match.group("count"))
    if not count:
        return None
    position: Literal["first", "last"] = "first" if match.group("position") == "first" else "last"
    return WindowSpec(position=position, count=count)


def window_rows(rows: list[Any], window: WindowSpec) -> list[Any]:
    """Truncate an already ordered population to one first/last N window.

    Player rows arrive DNP-filtered, so a team game the player missed never consumes a
    window slot and each player keeps their own N appearances. Game pools arrive sorted
    chronologically, so a N window is taken from the ordered population itself.
    """
    count = max(0, window.count)
    if not count:
        return []
    return rows[:count] if window.position == "first" else rows[-count:]


def _premise_count(normalized: str) -> int | None:
    match = _COUNT_PREMISE.search(normalized)
    if match is None:
        return None
    raw = match.group("count")
    return _NUMBER_WORDS.get(raw) or (int(raw) if raw.isdigit() else None)


def single_opponent_premise(
    question: str,
    *,
    opponents: tuple[str, ...],
    games: list[Any],
) -> ComparisonResolution:
    """A stated game count the requested scope contradicts is a question, not a scope.

    `games` is the population the request already narrowed (date, venue, phase, result),
    never the whole release: "the two games against Boston in January" is consistent with
    two January games even when the release holds more against Boston.
    """
    if len(opponents) != 1:
        return ComparisonResolution()
    normalized = normalize_text(question.replace("–", "-").replace("—", "-"))
    if WINDOW_ASK.search(normalized):
        return ComparisonResolution()
    claimed = _premise_count(normalized)
    if claimed is None:
        return ComparisonResolution()
    opponent = opponents[0]
    matching = sorted(
        (game for game in games if opponent in (game.home_team_id, game.away_team_id)),
        key=lambda game: (game.game_date, game.id),
    )
    if len(matching) == claimed:
        return ComparisonResolution()
    options = tuple(
        f"{game.game_date}: {game.away_team_id} at {game.home_team_id}" for game in matching
    ) or ("No archived games in this scope against that opponent.",)
    observed = (
        f"The games this request's own scope admits have {len(matching)} against "
        f"{opponent}, not {claimed}."
        if matching
        else f"The games this request's own scope admits have none against {opponent}."
    )
    return ComparisonResolution(
        clarification=f"{observed} Which games should I use?",
        options=options,
    )
