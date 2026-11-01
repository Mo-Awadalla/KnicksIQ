"""Typed grouped comparisons resolved from the question before plain filters collapse.

A comparison names two or more populations and one measure. The populations are typed
groups (home and away, two opponents, first and last windows, the two sides of the
All-Star break, the two conferences, named months, a recent window against the season),
so every group keeps its own games, record and denominator. Nothing here sums the groups
into one population or reads a question example.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from app.services.query_comparison_specs import (
    MONTH_LABELS,
    MONTH_NAMES,
    ComparisonContext,
    ComparisonFilters,
    ComparisonGroup,
    ComparisonMeasure,
    ComparisonResolution,
    ComparisonSpec,
    GroupKind,
    PopulationCoverage,
    TeamMeasure,
    WindowSpec,
)
from app.services.query_comparison_windows import WINDOW_ASK, window_rows
from app.services.query_operations import normalize_text

_ALL_STAR = re.compile(r"\ball[ -]?stars?\b")
_BENCH = re.compile(r"\bbench\b|\breserves?\b|\bnon[ -]?starters?\b|\bsecond unit\b|\bsubs?\b")
_HOME = re.compile(r"\bhome\b")
_AWAY = re.compile(r"\b(?:road|away)\b")
_EAST = re.compile(r"\beastern\b|\beast\b")
_WEST = re.compile(r"\bwestern\b|\bwest\b")
_BEFORE = re.compile(r"\bbefore\b")
_AFTER = re.compile(r"\bafter\b")
_SEASON = re.compile(r"\bseason\b")
_PHASE_SEASON = re.compile(r"\b(?:regular|post)[ -]?season\b")

# A player comparison windows observed appearances, which the game-window grammar never
# matches: "his last 2 appearances" is a unit of rows, not of team games.
_APPEARANCE_WINDOW = re.compile(
    r"\b(?P<position>first|last|final|previous)\s+(?P<count>\d{1,2})\s+"
    r"(?:observed\s+|nba\s+)?appearances?\b"
)


def appearance_window(normalized: str) -> WindowSpec | None:
    """The one first/last N appearance window a question names, if exactly one."""
    matches = list(_APPEARANCE_WINDOW.finditer(normalized))
    if len(matches) != 1:
        return None
    count = int(matches[0].group("count"))
    if not count:
        return None
    position: Literal["first", "last"] = (
        "first" if matches[0].group("position") == "first" else "last"
    )
    return WindowSpec(position=position, count=count)


def all_star_break(games: list[Any]) -> tuple[date | None, date | None]:
    """The archive's mid-February schedule gap, as the before and after boundaries."""
    february = sorted({game.game_date for game in games if game.game_date.month == 2})
    gaps = [
        (after - before, before, after)
        for before, after in zip(february, february[1:], strict=False)
        if 8 <= before.day <= 18 and 14 <= after.day <= 25
    ]
    if not gaps:
        return None, None
    _, before, after = max(gaps)
    return before, after


def _coverage_allows(coverage: PopulationCoverage, game: Any) -> bool:
    if coverage == "regular":
        return game.season_type == "regular"
    if coverage == "playoffs":
        return game.season_type in {"playoffs", "play_in"}
    return True


def _opponent(game: Any) -> str:
    return game.away_team_id if game.home_team_id == "NYK" else game.home_team_id


def comparison_pool(spec: ComparisonSpec, games: list[Any]) -> list[Any]:
    """Every game the request admits before its split axis is applied, chronologically.

    The coverage, the shared filters and a shared team-game window are the one population
    authority; a group only narrows this pool along its own axis. An appearance window is
    not a game window, so it never truncates here: it is taken over each player's
    observed rows before the split.
    """
    pool = [
        game
        for game in games
        if _coverage_allows(spec.coverage, game) and spec.filters.admits(game)
    ]
    pool.sort(key=lambda game: (game.game_date, game.id))
    if spec.filters.window is not None and spec.basis == "team_game":
        return window_rows(pool, spec.filters.window)
    return pool


def group_games(
    spec: ComparisonSpec,
    group: ComparisonGroup,
    games: list[Any],
    conferences: dict[str, str] | None = None,
) -> list[Any]:
    """The games one typed group selects, in chronological order.

    A window is applied exactly once, at the basis the comparison declares: a team-game
    window truncates here, while a player-appearance window leaves the group pool intact
    because appearances are only known after zero-minute rows are dropped.
    """
    pool = comparison_pool(spec, games)
    if group.kind == "home_away":
        home = group.home_away == "home"
        return [game for game in pool if (game.home_team_id == "NYK") == home]
    if group.kind == "opponent":
        return [
            game for game in pool if group.opponent_id in (game.home_team_id, game.away_team_id)
        ]
    if group.kind == "conference":
        mapping = conferences or {}
        return [game for game in pool if mapping.get(_opponent(game), "") == group.conference]
    if group.kind == "month":
        return [game for game in pool if game.game_date.month == group.month]
    if group.kind == "all_star":
        if group.phase == "before_all_star":
            return [
                game
                for game in pool
                if spec.break_before is not None and game.game_date <= spec.break_before
            ]
        return [
            game
            for game in pool
            if spec.break_after is not None and game.game_date >= spec.break_after
        ]
    if group.kind == "window" and group.window is not None and spec.basis == "team_game":
        return window_rows(pool, group.window)
    return pool


def _home_away(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    if not (_HOME.search(ctx.normalized) and _AWAY.search(ctx.normalized)):
        return None
    return (
        ComparisonGroup(key="home", label="At home", kind="home_away", home_away="home"),
        ComparisonGroup(key="away", label="On the road", kind="home_away", home_away="away"),
    )


def _opponents(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    if len(ctx.opponents) < 2:
        return None
    return tuple(
        ComparisonGroup(
            key=opponent,
            label=f"Against {opponent}",
            kind="opponent",
            opponent_id=opponent,
        )
        for opponent in ctx.opponents
    )


def _windows(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    seen: dict[str, WindowSpec] = {}
    for match in WINDOW_ASK.finditer(ctx.normalized):
        position: Literal["first", "last"] = (
            "first" if match.group("position") == "first" else "last"
        )
        count = int(match.group("count"))
        if count:
            seen.setdefault(f"{position}:{count}", WindowSpec(position=position, count=count))
    if len({window.position for window in seen.values()}) < 2:
        return None
    return tuple(
        ComparisonGroup(
            key=key,
            label=(
                f"First {window.count} games"
                if window.position == "first"
                else f"Last {window.count} games"
            ),
            kind="window",
            window=window,
        )
        for key, window in seen.items()
    )


def _recent_against_season(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    # "Regular season" names a phase, not the season baseline of a window comparison.
    baseline_text = _PHASE_SEASON.sub(" ", ctx.normalized)
    if not _SEASON.search(baseline_text):
        return None
    matches = list(WINDOW_ASK.finditer(ctx.normalized))
    if len(matches) != 1:
        return None
    match = matches[0]
    count = int(match.group("count"))
    if not count:
        return None
    position: Literal["first", "last"] = "first" if match.group("position") == "first" else "last"
    label = "First" if position == "first" else "Last"
    return (
        ComparisonGroup(
            key=f"{position}:{count}",
            label=f"{label} {count} games",
            kind="window",
            window=WindowSpec(position=position, count=count),
        ),
        ComparisonGroup(key="season", label="Across the season", kind="whole_season"),
    )


def _all_star(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    if not _ALL_STAR.search(ctx.normalized):
        return None
    if not (_BEFORE.search(ctx.normalized) and _AFTER.search(ctx.normalized)):
        return None
    if ctx.break_before is None or ctx.break_after is None:
        return None
    return (
        ComparisonGroup(
            key="before_all_star",
            label="Before the All-Star break",
            kind="all_star",
            phase="before_all_star",
        ),
        ComparisonGroup(
            key="after_all_star",
            label="After the All-Star break",
            kind="all_star",
            phase="after_all_star",
        ),
    )


def _conferences(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    if not (_EAST.search(ctx.normalized) and _WEST.search(ctx.normalized)):
        return None
    return (
        ComparisonGroup(
            key="East",
            label="Against Eastern teams",
            kind="conference",
            conference="East",
        ),
        ComparisonGroup(
            key="West",
            label="Against Western teams",
            kind="conference",
            conference="West",
        ),
    )


_INTERVAL_ASK = re.compile(r"\b(?:between|from|through|thru|until|till|since)\b")
_MONTH_DAY_ASK = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in MONTH_NAMES) + r")\s+\d{1,2}\b"
)
_COMPARISON_ASK = re.compile(
    r"\b(?:compare|comparison|versus|vs|difference|better|worse|fewer|more|higher|lower)\b"
)


def _months(ctx: ComparisonContext) -> tuple[ComparisonGroup, ...] | None:
    """Two named months split only when the ask compares them.

    "Between January 1 and March 15" or "from January through March" is one inclusive
    interval, and a bare mention of two months without a comparison is not a split.
    """
    if len(ctx.months) < 2:
        return None
    if _INTERVAL_ASK.search(ctx.normalized) or _MONTH_DAY_ASK.search(ctx.normalized):
        return None
    if not _COMPARISON_ASK.search(ctx.normalized):
        return None
    return tuple(
        ComparisonGroup(
            key=f"month:{month}",
            label=f"In {MONTH_LABELS[month]}",
            kind="month",
            month=month,
        )
        for month in ctx.months
    )


# Ordered so a more specific pairing wins: the All-Star break before any generic window,
# and a recent-versus-season ask before the same window could be read as a pairing.
_GROUP_RULES = (
    _all_star,
    _recent_against_season,
    _home_away,
    _conferences,
    _opponents,
    _windows,
    _months,
)


def _coverage(ctx: ComparisonContext) -> PopulationCoverage:
    if re.search(r"\bplayoffs?\b|\bpostseason\b", ctx.normalized):
        return "playoffs"
    if re.search(r"\bregular season\b", ctx.normalized):
        return "regular"
    return "release"


def _measure(ctx: ComparisonContext) -> ComparisonMeasure:
    if ctx.has_player:
        return "player_metric"
    if _BENCH.search(ctx.normalized):
        return "bench_points"
    return "scoring"


_OFFENSE = re.compile(r"\b(?:offen[cs]e|offensive|scoring|scored|score|points?)\b")
_DEFENSE = re.compile(r"\b(?:defen[cs]e|defensive|allowed)\b")
_MARGIN = re.compile(r"\b(?:margins?|differentials?)\b")
_JUDGEMENT = re.compile(r"\b(?:better|worse|fare|fares|fared|out-?played|out-?scored)\b")


def _team_measure(ctx: ComparisonContext) -> TeamMeasure:
    """The one team stat the question names; never a blended profile.

    An explicit offense, defense or margin ask keeps its own stat, and a stated total
    stays a total. Nothing explicit leaves how the groups fared, which is the record; a
    judgement ask adds the mean margin and states that neither measure settles it alone.
    """
    total = ctx.aggregation == "total"
    if _MARGIN.search(ctx.normalized):
        return "margin" if total else "margin_per_game"
    if _DEFENSE.search(ctx.normalized):
        return "points_allowed" if total else "points_allowed_per_game"
    if _OFFENSE.search(ctx.normalized):
        return "points" if total else "points_per_game"
    return "record_and_margin" if _JUDGEMENT.search(ctx.normalized) else "record"


# The scope field each group rule owns. A field owned by the split axis stays out of the
# shared filters, because filtering on it would collapse the groups it defines.
_AXIS_FIELDS: dict[GroupKind, frozenset[str]] = {
    "home_away": frozenset({"home_away"}),
    "opponent": frozenset({"opponent_id"}),
    "conference": frozenset({"opponent_id"}),
    "month": frozenset({"date_start", "date_end"}),
    "all_star": frozenset({"date_start", "date_end"}),
    "window": frozenset(),
    "whole_season": frozenset(),
}
# Group kinds that own the window axis: the window pairing and the recent-versus-season
# pairing both truncate their own population, so a shared window would double-apply.
_WINDOW_AXIS_KINDS = frozenset({"window", "whole_season"})


def _shared_filters(
    ctx: ComparisonContext,
    groups: tuple[ComparisonGroup, ...],
) -> ComparisonFilters:
    owned: set[str] = set()
    for group in groups:
        owned |= _AXIS_FIELDS[group.kind]
    dates_owned = bool({"date_start", "date_end"} & owned)
    single_opponent = ctx.opponents[0] if len(ctx.opponents) == 1 else None
    # A window comparison owns its window in the groups, so it is never repeated here.
    # Any other comparison keeps the shared window, whatever its basis: a team-game
    # window truncates the game pool, an appearance window truncates the player's
    # observed rows, and both are applied before the split.
    window_axis = any(group.kind in _WINDOW_AXIS_KINDS for group in groups)
    return ComparisonFilters(
        opponent_id=None if "opponent_id" in owned else single_opponent,
        date_start=None if dates_owned else ctx.date_start,
        date_end=None if dates_owned else ctx.date_end,
        season_type=ctx.season_type,
        home_away=None if "home_away" in owned else ctx.home_away,
        game_result=ctx.game_result,
        window=ctx.window if ctx.window is not None and not window_axis else None,
    )


def resolve_comparison(
    question: str,
    *,
    opponents: tuple[str, ...],
    has_player: bool,
    metric: str | None,
    games: list[Any],
    stat: str | None = None,
    aggregation: Literal["average", "total"] | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
    season_type: Literal["regular", "play_in", "playoffs"] | None = None,
    home_away: Literal["home", "away"] | None = None,
    game_result: Literal["W", "L"] | None = None,
    window: WindowSpec | None = None,
) -> ComparisonResolution:
    """Resolve a typed grouped comparison, or nothing when the ask is not one."""
    normalized = normalize_text(question.replace("–", "-").replace("—", "-"))
    # "His last 2 appearances" is one window at the appearance basis; the game-window
    # grammar the caller reads never matches it, so it is read here.
    window = window or appearance_window(normalized)
    break_before, break_after = all_star_break(games)
    months = tuple(
        sorted(
            {
                month
                for name, month in MONTH_NAMES.items()
                if re.search(rf"\b{re.escape(name)}\b", normalized)
            }
        )
    )
    ctx = ComparisonContext(
        normalized=normalized,
        opponents=tuple(sorted(opponents)),
        has_player=has_player,
        metric=metric,
        break_before=break_before,
        break_after=break_after,
        months=months,
        stat=stat,
        aggregation=aggregation,
        date_start=date_start,
        date_end=date_end,
        season_type=season_type,
        home_away=home_away,
        game_result=game_result,
        window=window,
    )
    for rule in _GROUP_RULES:
        groups = rule(ctx)
        if groups is None:
            continue
        measure = _measure(ctx)
        basis: Literal["team_game", "player_appearance"] = (
            "player_appearance" if measure == "player_metric" else "team_game"
        )
        return ComparisonResolution(
            spec=ComparisonSpec(
                measure=measure,
                groups=groups,
                metric=(ctx.metric or "points") if ctx.has_player else None,
                stat=ctx.stat,
                aggregation=ctx.aggregation,
                team_metric=_team_measure(ctx) if measure == "scoring" else None,
                basis=basis,
                filters=_shared_filters(ctx, groups),
                coverage=_coverage(ctx),
                break_before=break_before,
                break_after=break_after,
            )
        )
    return ComparisonResolution()
