"""The typed comparison a question names: its measure, groups and shared filters.

Every group keeps its own games, record and denominator, so the spec carries the axis
each group owns and the constraints no group owns. Nothing here reads a question; the
group rules in `query_comparisons` build these values and the tools consume them.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GroupKind = Literal[
    "home_away",
    "opponent",
    "window",
    "all_star",
    "conference",
    "month",
    "whole_season",
]
ComparisonMeasure = Literal["scoring", "bench_points", "player_metric"]
# The one team stat a grouped comparison asks for. A question that names no stat asks how
# the groups fared, which is a record; one that asks who fared better gets the record and
# the mean margin as separate facts, never a single invented overall judgement.
TeamMeasure = Literal[
    "points_per_game",
    "points",
    "points_allowed_per_game",
    "points_allowed",
    "margin_per_game",
    "margin",
    "record",
    "record_and_margin",
]
TeamClaimMetric = Literal[
    "points_per_game",
    "points",
    "points_allowed_per_game",
    "points_allowed",
    "margin_per_game",
    "margin",
    "wins",
    "losses",
    "bench_points_per_team_game",
]
PopulationCoverage = Literal["release", "regular", "playoffs"]
GroupPhase = Literal["before_all_star", "after_all_star"]

MONTH_NAMES: dict[str, int] = {
    name.lower(): index for index, name in enumerate(calendar.month_name) if name
}
MONTH_LABELS = {index: name for index, name in enumerate(calendar.month_name) if name}

# The exact claim metric ids one team measure emits per group. A record is two facts over
# the same games, not one blended score, and a judgement ask keeps them apart too.
_TEAM_CLAIM_METRICS: dict[str, tuple[TeamClaimMetric, ...]] = {
    "points_per_game": ("points_per_game",),
    "points": ("points",),
    "points_allowed_per_game": ("points_allowed_per_game",),
    "points_allowed": ("points_allowed",),
    "margin_per_game": ("margin_per_game",),
    "margin": ("margin",),
    "record": ("wins", "losses"),
    "record_and_margin": ("wins", "losses", "margin_per_game"),
}


class WindowSpec(BaseModel):
    """One direction-and-count window over chronological games or appearances."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: Literal["first", "last"]
    count: int


class ComparisonGroup(BaseModel):
    """One population of a comparison, with the rule that selects its games."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    kind: GroupKind
    home_away: Literal["home", "away"] | None = None
    opponent_id: str | None = None
    window: WindowSpec | None = None
    phase: GroupPhase | None = None
    conference: Literal["East", "West"] | None = None
    month: int | None = None


class ComparisonFilters(BaseModel):
    """The request's shared constraints, minus whichever axis the groups split.

    "Compare home and away scoring against Boston in January" splits home from away over
    Boston games in January: the opponent and the interval stay here, so no group ever
    falls back to the whole release. A field is absent exactly when a group rule owns it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    opponent_id: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    # The first or last N of the population a question names, applied once before any
    # group splits it. It is not a per-game predicate, so `admits` ignores it. A team-game
    # window truncates the sorted game pool; an appearance window truncates each player's
    # observed chronological appearances, so a DNP never consumes a slot and both sides of
    # a split see the same window. A window a group owns is never repeated here.
    window: WindowSpec | None = None

    def admits(self, game: Any) -> bool:
        if self.opponent_id and self.opponent_id not in (game.home_team_id, game.away_team_id):
            return False
        if self.date_start and game.game_date < self.date_start:
            return False
        if self.date_end and game.game_date > self.date_end:
            return False
        if self.season_type and game.season_type != self.season_type:
            return False
        home = game.home_team_id == "NYK"
        if self.home_away and home != (self.home_away == "home"):
            return False
        if self.game_result:
            own, other = (
                (game.home_score, game.away_score) if home else (game.away_score, game.home_score)
            )
            if (own > other) != (self.game_result == "W"):
                return False
        return True


class ComparisonSpec(BaseModel):
    """The measure and the ordered groups of one grouped comparison request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    measure: ComparisonMeasure
    groups: tuple[ComparisonGroup, ...]
    metric: str | None = None
    # The specific statistic and aggregation the user asked for. They are never replaced
    # by the measure's default: a three-point percentage stays a ratio, and a requested
    # total is not delivered as an average.
    stat: str | None = None
    aggregation: Literal["average", "total"] | None = None
    # The unit each window truncates. A player comparison windows appearances after DNPs
    # are removed, so a missed team game never consumes one of the N slots.
    basis: Literal["team_game", "player_appearance"] = "team_game"
    # The one stat a team measure answers with. It is absent for a player or bench
    # comparison, which carry their own measure, and never invented for one.
    team_metric: TeamMeasure | None = None
    filters: ComparisonFilters = Field(default_factory=ComparisonFilters)
    coverage: PopulationCoverage = "release"
    break_before: date | None = None
    break_after: date | None = None


def team_claim_metrics(spec: ComparisonSpec) -> tuple[TeamClaimMetric, ...]:
    """The exact metric ids one group of this team comparison emits.

    A team comparison that names no recorded stat asks how the groups fared, which is the
    record; it never falls back to a blended profile of every component.
    """
    if spec.measure == "bench_points":
        return ("bench_points_per_team_game",)
    return _TEAM_CLAIM_METRICS[spec.team_metric or "record"]


@dataclass(frozen=True)
class ComparisonResolution:
    """The typed comparison, or the clarification that would make one answerable."""

    spec: ComparisonSpec | None = None
    clarification: str | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComparisonContext:
    """Question-derived facts the group rules read; no rule parses wording itself."""

    normalized: str
    opponents: tuple[str, ...]
    has_player: bool
    metric: str | None
    break_before: date | None
    break_after: date | None
    months: tuple[int, ...]
    stat: str | None = None
    aggregation: Literal["average", "total"] | None = None
    date_start: date | None = None
    date_end: date | None = None
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    window: WindowSpec | None = None
