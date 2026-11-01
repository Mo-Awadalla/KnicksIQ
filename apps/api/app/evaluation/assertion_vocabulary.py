"""Metric and scope vocabulary for typed assertion checks.

The metric aliases accept only explicit runtime metric-id token sets, and the
scope grammar accepts only the vocabulary the labels actually use; anything else
is reported as unexpressible instead of being guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

TEAM_CODES = frozenset(
    {
        "ATL",
        "BOS",
        "BKN",
        "CHA",
        "CHI",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GSW",
        "HOU",
        "IND",
        "LAC",
        "LAL",
        "MEM",
        "MIA",
        "MIL",
        "MIN",
        "NOP",
        "NYK",
        "OKC",
        "ORL",
        "PHI",
        "PHX",
        "POR",
        "SAC",
        "SAS",
        "TOR",
        "UTA",
        "WAS",
    }
)

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

ALL_STAR_BREAK = date(2026, 2, 15)


@dataclass(frozen=True)
class MetricAlias:
    """Accepted runtime metric-id token sets and units for one label metric."""

    tokens: tuple[frozenset[str], ...]
    units: frozenset[str]


def _alias(tokens: list[set[str]], units: set[str]) -> MetricAlias:
    return MetricAlias(tuple(frozenset(item) for item in tokens), frozenset(units))


METRIC_ALIASES: dict[str, MetricAlias] = {
    "wins": _alias([{"wins"}, {"wins", "total"}], {"wins", "wins per game"}),
    "losses": _alias([{"losses"}, {"losses", "total"}], {"losses"}),
    "games": _alias([{"games"}, {"game", "count"}], {"games"}),
    "game_count": _alias([{"games"}, {"game", "count"}], {"games"}),
    "margin": _alias(
        [
            {"margin"},
            {"margin", "average"},
            {"margin", "per", "game"},
            # A ranking states the extreme under its own metric id: a largest win keeps
            # the canonical sign, a largest loss states its own deficit as a magnitude.
            {"win", "margin"},
            {"loss", "margin"},
        ],
        {"points", "points per game"},
    ),
    "average_margin": _alias(
        [{"margin", "average"}, {"margin", "per", "game"}, {"margin"}],
        {"points", "points per game"},
    ),
    "margin_per_game": _alias(
        [{"margin", "per", "game"}, {"margin", "average"}, {"margin"}],
        {"points", "points per game"},
    ),
    "points": _alias(
        [{"points"}, {"points", "total"}, {"points", "per", "game"}, {"points", "average"}],
        {"points", "points per game", "points per appearance"},
    ),
    "average_points": _alias(
        [{"points", "average"}, {"points", "per", "game"}, {"points"}],
        {"points", "points per game", "points per appearance"},
    ),
    "total_points": _alias([{"points", "total"}, {"points"}, {"points", "game"}], {"points"}),
    "points_per_game": _alias(
        [{"points", "per", "game"}, {"points", "average"}, {"points"}],
        {"points", "points per game"},
    ),
    "points_allowed_per_game": _alias(
        [
            {"points", "allowed", "per", "game"},
            {"points", "allowed", "average"},
            {"points", "allowed"},
            {"opponent", "points", "average"},
        ],
        {"points", "points per game"},
    ),
    "points_allowed": _alias([{"points", "allowed"}, {"points", "allowed", "total"}], {"points"}),
    "turnovers_per_game": _alias(
        [{"turnovers", "per", "game"}, {"turnovers", "average"}, {"turnovers"}],
        {"turnovers", "turnovers per game", "turnovers per appearance"},
    ),
    "bench_points_per_team_game": _alias(
        [{"bench", "points"}, {"bench", "points", "per", "team", "game"}],
        {"points", "points per game"},
    ),
    "period_points_per_game": _alias(
        [{"period", "points"}, {"period", "points", "per", "game"}],
        {"points", "points per game"},
    ),
    "field_goal_percentage": _alias(
        [{"field", "goal", "percentage"}, {"fg", "percentage"}, {"field", "goal", "pct"}],
        {"percent", "percentage", "pct", "%"},
    ),
    "three_point_percentage": _alias(
        [{"three", "point", "percentage"}, {"three", "points", "percentage"}],
        {"percent", "percentage", "pct", "%"},
    ),
    "free_throw_percentage": _alias(
        [{"free", "throw", "percentage"}], {"percent", "percentage", "pct", "%"}
    ),
    "true_shooting_percentage": _alias(
        [{"true", "shooting", "percentage"}, {"true", "shooting", "pct"}],
        {"percent", "percentage", "pct", "%"},
    ),
    "percentage_three_pointers_made": _alias(
        [
            {"three", "pointers", "made", "percentage"},
            {"three", "pointers", "made", "pct"},
            {"three", "point", "percentage"},
        ],
        {"percent", "percentage", "pct", "%"},
    ),
    "average_rebounds": _alias(
        [{"rebounds", "average"}, {"rebounds", "per", "game"}, {"rebounds", "per", "appearance"}],
        {"rebounds", "rebounds per game", "rebounds per appearance"},
    ),
    "total_rebounds": _alias(
        [{"rebounds", "total"}, {"rebounds"}, {"rebounds", "game"}], {"rebounds"}
    ),
    "average_assists": _alias(
        [{"assists", "average"}, {"assists", "per", "game"}, {"assists", "per", "appearance"}],
        {"assists", "assists per game", "assists per appearance"},
    ),
    "total_assists": _alias([{"assists", "total"}, {"assists"}, {"assists", "game"}], {"assists"}),
    "double_doubles_points": _alias(
        [{"double", "doubles"}, {"points", "double", "doubles"}],
        {"double_doubles", "count", "double doubles"},
    ),
    "starts_starter": _alias([{"starts"}, {"starter"}], {"starts", "count"}),
    "assists_leader": _alias([{"assists", "leader"}], {"assists", "assists per game"}),
    "points_leader": _alias([{"points", "leader"}], {"points", "points per game"}),
    "rebounds_leader": _alias([{"rebounds", "leader"}], {"rebounds", "rebounds per game"}),
    "steals_leader": _alias([{"steals", "leader"}], {"steals", "steals per game"}),
}

DICT_METRICS = frozenset({"game_score"})


def metric_key(metric: str) -> str:
    """Normalise a label metric, dropping a leading ``Player:`` prefix."""
    remainder = metric.split(": ", 1)[1] if ": " in metric else metric
    return re.sub(r"\s+", "_", remainder.strip().casefold())


@dataclass(frozen=True)
class ScopeExpectation:
    raw: str
    parseable: bool
    opponent: str | None = None
    conference: str | None = None
    month: int | None = None
    year: int | None = None
    after: date | None = None
    before_all_star: bool = False
    after_all_star: bool = False
    include_postseason: bool = False
    first_n: int | None = None
    last_n: int | None = None
    appearances: bool = False
    venue: Literal["home", "away"] | None = None
    road: bool = False
    result: Literal["win", "loss"] | None = None
    period: int | None = None


def parse_scope(scope: str) -> ScopeExpectation:
    """Explicit scope vocabulary; anything else is unexpressible and fails closed."""
    raw = scope.strip()
    lowered = raw.casefold()
    if lowered == "archive":
        return ScopeExpectation(raw, True)
    base: dict[str, Any] = {"raw": raw, "parseable": True}
    if raw.upper() in TEAM_CODES:
        return ScopeExpectation(**{**base, "opponent": raw.upper()})
    if lowered in {"east", "west"}:
        return ScopeExpectation(**{**base, "conference": lowered.title()})
    if lowered in {"home", "away"}:
        return ScopeExpectation(**{**base, "venue": lowered})
    if lowered in {"wins", "losses"}:
        return ScopeExpectation(**{**base, "result": "win" if lowered == "wins" else "loss"})
    if lowered in {"season appearances", "last appearances"}:
        return ScopeExpectation(**{**base, "appearances": True})
    period = re.fullmatch(r"quarter (\d)", lowered)
    if period:
        return ScopeExpectation(**{**base, "period": int(period.group(1))})
    sample = re.fullmatch(r"(first|last) (\d+) (games|appearances)", lowered)
    if sample:
        key = "first_n" if sample.group(1) == "first" else "last_n"
        return ScopeExpectation(
            **{**base, key: int(sample.group(2)), "appearances": sample.group(3) == "appearances"}
        )
    month = re.fullmatch(r"([a-z]+) (\d{4})", lowered)
    if month and month.group(1) in MONTHS:
        return ScopeExpectation(
            **{**base, "month": MONTHS[month.group(1)], "year": int(month.group(2))}
        )
    road = re.fullmatch(r"([a-z]+) road games", lowered)
    if road and road.group(1) in MONTHS:
        return ScopeExpectation(
            **{**base, "month": MONTHS[road.group(1)], "road": True, "venue": "away"}
        )
    boundary = re.fullmatch(
        r"(before|after) (?:all-star break|february 15, 2026)"
        r"(?: \(?(including postseason)\)?)?",
        lowered,
    )
    if boundary:
        return ScopeExpectation(
            **{
                **base,
                "before_all_star": boundary.group(1) == "before",
                "after_all_star": boundary.group(1) == "after",
                "include_postseason": bool(boundary.group(2)),
                "after": ALL_STAR_BREAK if boundary.group(1) == "after" else None,
            }
        )
    return ScopeExpectation(raw, False)
