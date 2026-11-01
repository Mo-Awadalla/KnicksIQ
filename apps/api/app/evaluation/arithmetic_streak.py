"""Streaks: the consecutive win or loss runs inside one considered population.

The runs are scanned from the final scores in archive order, so a population that is
not date-ordered — or that cannot supply a score — blocks instead of describing a run
it cannot see. A tied longest run is reported whole, and a run claim must cite one of
the tied runs exactly.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    ELIGIBILITY_UNVERIFIED,
    EXPANSION_MISMATCH,
    HOME_TEAM,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SCOPE_MISMATCH,
    ClaimView,
    Population,
    Proof,
    blocked,
    counts_as,
    declared_ids,
    population_invalid,
    same,
    team_score,
    tolerance,
)

STREAKS = {
    "winning_streak_length": ("winning", True),
    "losing_streak_length": ("losing", True),
    "winning_streak": ("winning", False),
    "losing_streak": ("losing", False),
}


def prove(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof | None:
    """One streak recipe, or None when this claim is not one."""
    if view.metric not in STREAKS:
        return None
    return _streak(view, rows, population)


def _streak(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    direction, whole = STREAKS[view.metric]
    if view.sample_size is None:
        return blocked(POPULATION_UNVERIFIED)
    considered = declared_ids(view.eligibility.get("considered_game_ids"))
    if considered is None:
        return blocked(ELIGIBILITY_UNVERIFIED)
    missing = population.gap()
    if missing:
        return blocked(missing)
    keys = [population.order(game_id) for game_id in considered]
    if any(key is None for key in keys):
        return blocked(POPULATION_UNVERIFIED)
    days = [key[0] for key in keys if key is not None]
    if days != sorted(days):
        # The producer scans its population in archive order; a population that is not
        # date-ordered cannot describe consecutive runs at all.
        return blocked(POPULATION_UNVERIFIED)
    ordered = list(considered)
    runs, reason = _runs(ordered, direction, population)
    if reason:
        return blocked(reason)
    longest = max((len(run) for run in runs), default=0)
    tied = [run for run in runs if len(run) == longest]
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    recipe = "streak_length" if whole else "streak_run"
    problems: list[str] = []
    if whole:
        expected = [game for run in tied for game in run]
        if not same(view.value, float(longest), tolerance(view.decimals)):
            problems.append(ARITHMETIC_MISMATCH)
    else:
        expected_run = _cited_run(cited, ordered)
        if expected_run is None or expected_run not in tied:
            problems.append(SCOPE_MISMATCH)
            expected = []
        else:
            expected = expected_run
        if not same(view.value, float(longest), tolerance(view.decimals)):
            problems.append(ARITHMETIC_MISMATCH)
    if set(cited) != set(expected):
        problems.append(EXPANSION_MISMATCH)
    if set(view.game_ids) != set(expected):
        problems.append(SCOPE_MISMATCH)
    if not counts_as(view.sample_size, len(considered)):
        problems.append(POPULATION_MISMATCH)
    if view.denominator is not None:
        problems.append(POPULATION_MISMATCH)
    if problems:
        return population_invalid(problems, recipe)
    return Proof("verified", recipe, population_cited=True)


def _runs(
    ordered: list[int], direction: str, population: Population
) -> tuple[list[list[int]], str | None]:
    runs: list[list[int]] = []
    current: list[int] = []
    for game_id in ordered:
        row = population.games.get(game_id)
        score = team_score(row.row, HOME_TEAM) if row is not None else None
        if score is None:
            return [], POPULATION_UNVERIFIED
        own, other = score
        matched = own < other if direction == "losing" else own > other
        if matched:
            current.append(game_id)
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs, None


def _cited_run(cited: tuple[int, ...], ordered: list[int]) -> list[int] | None:
    """The cited games as one consecutive run, or None when they are not one."""
    position = {game_id: index for index, game_id in enumerate(ordered)}
    if any(game_id not in position for game_id in cited):
        return None
    indexes = sorted(position[game_id] for game_id in cited)
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        return None
    return [ordered[index] for index in indexes]
