"""Box-score arithmetic: weighted rates, derived ratios and column aggregates.

A percentage is never the mean of per-appearance percentages and never the reported
made/attempted pair alone: it is recomputed from the cited rows as a weighted rate over
the shot or possession opportunities the rows themselves hold.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    ELIGIBILITY_UNVERIFIED,
    EXPANSION_MISMATCH,
    MISSING_FIELDS,
    PLAYER,
    SCOPE_MISMATCH,
    SUBJECT_MISMATCH,
    TEAM,
    UNSUPPORTED,
    ClaimView,
    Proof,
    aggregation_suffix,
    blocked,
    declaration,
    declared_ids,
    invalid,
    number,
    player_of,
    same,
    team_of,
    tolerance,
)

PLAYER_FIELDS = frozenset(
    "points rebounds assists turnovers steals blocks minutes plus_minus "
    "offensive_rebounds defensive_rebounds personal_fouls field_goals_made "
    "field_goals_attempted three_pointers_made three_pointers_attempted "
    "free_throws_made free_throws_attempted".split()
)
TEAM_FIELDS = PLAYER_FIELDS - {"minutes"}
STAT_ALIASES = {
    "threes_made": "three_pointers_made",
    "threes_attempted": "three_pointers_attempted",
}
# Registry stat keys that are stored player columns, so a count aggregate can read them.
COUNT_COLUMNS = {field: field for field in PLAYER_FIELDS}
RATE_STATS = {
    "field_goal_percentage": ("field_goals_made", "field_goals_attempted"),
    "three_pointers_made:percentage": ("three_pointers_made", "three_pointers_attempted"),
    "free_throws_made:percentage": ("free_throws_made", "free_throws_attempted"),
}
DERIVED_STATS = frozenset(
    {"true_shooting_percentage", "effective_field_goal_percentage", "assist_turnover_ratio"}
)
COUNTED_STATS = frozenset({"double_doubles", "triple_doubles", "starts"})
STATLINE_SUFFIX = ":game"
MULTIPLE = ("points", "rebounds", "assists", "steals", "blocks")


def box_column(stat: str) -> str | None:
    """The stored column a registry count stat reads, or None when it is not one."""
    column = STAT_ALIASES.get(stat, stat)
    return column if column in COUNT_COLUMNS else None


def totals(rows: list[dict[str, Any]], *columns: str) -> list[float] | None:
    """Column sums over the rows, or None when any row cannot supply a number."""
    sums = [0.0] * len(columns)
    for row in rows:
        for index, column in enumerate(columns):
            item = row.get(column)
            if not number(item):
                return None
            sums[index] += float(item)
    return sums


def aggregate(
    rows: list[dict[str, Any]], stat: str, *, mean: bool = True
) -> tuple[float | None, str | None]:
    """One producer aggregate over appearances.

    ``(value, reason)`` describes a measurable value, an unprovable recipe or missing
    columns. ``(None, None)`` is a genuinely undefined value — a zero denominator — and
    the caller must never read it as a measured zero.
    """
    if not rows:
        return None, None
    if stat in RATE_STATS:
        sums = totals(rows, *RATE_STATS[stat])
        if sums is None:
            return None, MISSING_FIELDS
        made, attempted = sums
        return (100.0 * made / attempted, None) if attempted else (None, None)
    if stat == "true_shooting_percentage":
        sums = totals(rows, "points", "field_goals_attempted", "free_throws_attempted")
        if sums is None:
            return None, MISSING_FIELDS
        points, attempts, free_throws = sums
        opportunities = 2.0 * (attempts + 0.44 * free_throws)
        return (100.0 * points / opportunities, None) if opportunities else (None, None)
    if stat == "effective_field_goal_percentage":
        sums = totals(rows, "field_goals_made", "three_pointers_made", "field_goals_attempted")
        if sums is None:
            return None, MISSING_FIELDS
        field_goals, threes, attempts = sums
        return (
            (100.0 * (field_goals + 0.5 * threes) / attempts, None)
            if attempts
            else (
                None,
                None,
            )
        )
    if stat == "assist_turnover_ratio":
        sums = totals(rows, "assists", "turnovers")
        if sums is None:
            return None, MISSING_FIELDS
        assists, turnovers = sums
        return (assists / turnovers, None) if turnovers else (None, None)
    column = box_column(stat)
    if column is None:
        return None, UNSUPPORTED
    sums = totals(rows, column)
    if sums is None:
        return None, MISSING_FIELDS
    return (sums[0] / len(rows) if mean else sums[0]), None


def prove_box(
    view: ClaimView, rows: list[dict[str, Any]], collections: list[str], player: Any
) -> Proof:
    """Prove one box-score claim from its cited rows alone."""
    kinds = set(collections)
    if kinds == {TEAM}:
        team = team_of(view.subject)
        if team is None or any(row.get("team_id") != team for row in rows):
            return invalid((SUBJECT_MISMATCH,))
        fields = TEAM_FIELDS
    elif kinds == {PLAYER}:
        if player_of(view.subject) is None:
            return invalid((SUBJECT_MISMATCH,))
        if player is None:
            return blocked("calculation_subject_unmapped")
        if any(str(row.get("nba_player_id")) != str(player) for row in rows):
            return invalid((SUBJECT_MISMATCH,))
        if view.metric in COUNTED_STATS:
            return _counted(view, rows)
        if view.metric.endswith(STATLINE_SUFFIX):
            return _statline(view, rows)
        fields = PLAYER_FIELDS
    else:
        return invalid((EXPANSION_MISMATCH,))
    return _aggregated(view, rows, fields)


def _aggregated(view: ClaimView, rows: list[dict[str, Any]], fields: frozenset[str]) -> Proof:
    base, aggregation = aggregation_suffix(view.metric)
    count = len(rows)
    if aggregation == "total" and (base in RATE_STATS or base in DERIVED_STATS):
        # A weighted rate has no meaningful total; only its own weighted value exists.
        return blocked(UNSUPPORTED)
    if base in RATE_STATS or base in DERIVED_STATS:
        return _rate(view, rows, base, count)
    column = box_column(base)
    if column is None or column not in fields:
        return blocked(UNSUPPORTED)
    if aggregation not in {"total", "average"}:
        return blocked(UNSUPPORTED)
    mean = aggregation == "average"
    values = totals(rows, column)
    if values is None:
        return blocked(MISSING_FIELDS)
    recipe = "box_column_mean" if mean else "box_column_total"
    if view.numerator is not None and abs(float(view.numerator) - values[0]) > 1e-9:
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    problems, reason = declaration(count, view.denominator, view.sample_size, mean=mean)
    expected = values[0] / count if mean else values[0]
    return _verdict(recipe, view, expected, problems, reason)


def _rate(view: ClaimView, rows: list[dict[str, Any]], base: str, count: int) -> Proof:
    recipes = {
        "true_shooting_percentage": "box_true_shooting",
        "effective_field_goal_percentage": "box_effective_field_goal",
        "assist_turnover_ratio": "box_assist_turnover",
    }
    recipe = recipes.get(base, "box_rate_weighted")
    value, reason = aggregate(rows, base)
    if reason:
        return blocked(reason)
    if value is None:
        # A zero denominator is not a measured zero, so the claim cannot be true.
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    extra: tuple[float, ...] = ()
    if base == "true_shooting_percentage":
        sums = totals(rows, "points", "field_goals_attempted", "free_throws_attempted")
        assert sums is not None
        extra = (2.0 * (sums[1] + 0.44 * sums[2]),)
    if base in RATE_STATS:
        sums = totals(rows, *RATE_STATS[base])
        assert sums is not None
        made, attempted = sums
        if (view.made is not None and abs(float(view.made) - made) > 1e-9) or (
            view.attempted is not None and abs(float(view.attempted) - attempted) > 1e-9
        ):
            return invalid((ARITHMETIC_MISMATCH,), recipe)
        if view.numerator is not None and abs(float(view.numerator) - made) > 1e-9:
            return invalid((ARITHMETIC_MISMATCH,), recipe)
    problems, reason = declaration(
        count, view.denominator, view.sample_size, mean=True, extra=extra
    )
    return _verdict(recipe, view, value, problems, reason)


def _statline(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    """One pinned game's own box-score value: the cited row's field, never a mean."""
    column = box_column(view.metric[: -len(STATLINE_SUFFIX)])
    if column is None:
        return blocked(UNSUPPORTED)
    if len(rows) != 1:
        # The shape is one game's own row; a statline is never summed over appearances.
        return blocked(UNSUPPORTED)
    pinned = declared_ids(view.eligibility.get("considered_game_ids"))
    if pinned is None:
        return blocked(ELIGIBILITY_UNVERIFIED)
    if len(pinned) != 1 or list(view.game_ids) != list(pinned):
        # A statline stands for exactly the one game its population declares.
        return invalid((SCOPE_MISMATCH,), "game_statline")
    item = rows[0].get(column)
    if not number(item):
        return blocked(MISSING_FIELDS)
    problems, reason = declaration(1, view.denominator, view.sample_size, mean=False)
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems, "game_statline")
    if not same(view.value, float(item), 1e-9):
        return invalid((ARITHMETIC_MISMATCH,), "game_statline")
    return Proof("verified", "game_statline")


def _counted(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    if view.metric == "starts":
        if any(not isinstance(row.get("starter"), bool) for row in rows):
            return blocked(MISSING_FIELDS)
        counted = sum(1 for row in rows if row["starter"])
        recipe = "box_starts"
    else:
        threshold = 2 if view.metric == "double_doubles" else 3
        counted = 0
        for row in rows:
            values: list[float] = []
            for column in MULTIPLE:
                item = row.get(column)
                if not number(item):
                    return blocked(MISSING_FIELDS)
                values.append(float(item))
            counted += sum(value >= 10 for value in values) >= threshold
        recipe = "box_multiples"
    problems, reason = declaration(len(rows), view.denominator, view.sample_size, mean=False)
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems, recipe)
    if not same(view.value, float(counted), 1e-9):
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    return Proof("verified", recipe)


def _verdict(
    recipe: str,
    view: ClaimView,
    expected: float,
    problems: list[str],
    reason: str | None,
) -> Proof:
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems, recipe)
    if not same(view.value, expected, tolerance(view.decimals)):
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    return Proof("verified", recipe)
