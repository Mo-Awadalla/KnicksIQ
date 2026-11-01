"""Threshold counts: how many games of the population met one stated cutoff.

The team recipe counts final scores in a considered population; the player recipe
counts one subject's qualifying appearances. Both recompute the count and the
considered denominator from the mapping's verified projection of the whole release
and hold them to the claim's own recorded sample.
"""

from __future__ import annotations

from operator import ge, gt, le, lt
from typing import Any

from app.evaluation.arithmetic_box import box_column
from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    ELIGIBILITY_UNVERIFIED,
    EXPANSION_MISMATCH,
    HOME_TEAM,
    MISSING_FIELDS,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SCOPE_MISMATCH,
    SUBJECT_MISMATCH,
    UNSUPPORTED,
    ClaimView,
    Population,
    Proof,
    blocked,
    counts_as,
    declared_ids,
    invalid,
    number,
    player_of,
    population_invalid,
    same,
    team_score,
    tolerance,
)

TEAM_SUBJECTS = frozenset({"own_points", "opponent_points", "margin", "deficit"})
COMPARATORS = {">=": ge, ">": gt, "<=": le, "<": lt}
THRESHOLD_SUFFIX = ":threshold"


def prove(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof | None:
    """One threshold count, or None when this claim is not one."""
    eligibility = view.eligibility
    if view.metric == "games" and "threshold" in eligibility and "comparator" in eligibility:
        return _threshold_team(view, rows, population)
    if view.metric.endswith(THRESHOLD_SUFFIX):
        return _threshold_player(view, rows, population)
    return None


def _threshold_team(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    eligibility = view.eligibility
    if view.sample_size is None or view.denominator is None:
        return blocked(POPULATION_UNVERIFIED)
    subject = eligibility.get("subject")
    comparator = eligibility.get("comparator")
    cutoff = eligibility.get("threshold")
    considered = declared_ids(eligibility.get("considered_game_ids"))
    declared = declared_ids(eligibility.get("matching_game_ids"))
    if (
        subject not in TEAM_SUBJECTS
        or comparator not in COMPARATORS
        or not number(cutoff)
        or considered is None
        or declared is None
    ):
        return blocked(ELIGIBILITY_UNVERIFIED)
    missing = population.gap()
    if missing:
        return blocked(missing)
    matching: list[int] = []
    for game_id in considered:
        row = population.games.get(game_id)
        score = team_score(row.row, HOME_TEAM) if row is not None else None
        if score is None:
            return blocked(POPULATION_UNVERIFIED)
        if _team_accepts(str(subject), str(comparator), float(cutoff), *score):
            matching.append(game_id)
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    problems: list[str] = []
    if set(cited) != set(considered):
        problems.append(EXPANSION_MISMATCH)
    if set(declared) != set(matching) or set(view.game_ids) != set(matching):
        problems.append(SCOPE_MISMATCH)
    if not counts_as(view.sample_size, len(matching)) or not counts_as(
        view.denominator, len(considered)
    ):
        problems.append(POPULATION_MISMATCH)
    if not same(view.value, float(len(matching)), tolerance(view.decimals)):
        problems.append(ARITHMETIC_MISMATCH)
    if problems:
        return population_invalid(problems, "team_threshold_count")
    return Proof("verified", "team_threshold_count", population_cited=True)


def _threshold_player(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    eligibility = view.eligibility
    if view.sample_size is None or view.denominator is None:
        return blocked(POPULATION_UNVERIFIED)
    comparator = eligibility.get("comparator")
    cutoff = eligibility.get("threshold")
    metric = eligibility.get("metric")
    considered = declared_ids(eligibility.get("considered_game_ids"))
    declared = declared_ids(eligibility.get("qualifying_game_ids"))
    subject = player_of(view.subject)
    if subject is None:
        return invalid((SUBJECT_MISMATCH,))
    if metric is None or comparator is None or cutoff is None:
        return blocked(ELIGIBILITY_UNVERIFIED)
    column = box_column(str(metric))
    if column is None:
        return blocked(UNSUPPORTED)
    if (
        comparator not in COMPARATORS
        or not number(cutoff)
        or considered is None
        or declared is None
    ):
        return blocked(ELIGIBILITY_UNVERIFIED)
    missing = population.gap(box=True)
    if missing:
        return blocked(missing)
    observed = population.appearances(subject, considered)
    if observed is None:
        return blocked(POPULATION_UNVERIFIED)
    values: list[float] = []
    for row in observed:
        item = row.row.get(column)
        if not number(item):
            return blocked(MISSING_FIELDS)
        values.append(float(item))
    accept = COMPARATORS[str(comparator)]
    qualifying = [
        row.game_id
        for row, value in zip(observed, values, strict=True)
        if accept(value, float(cutoff))
    ]
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    problems: list[str] = []
    if set(cited) != {row.game_id for row in observed}:
        problems.append(EXPANSION_MISMATCH)
    if set(declared) != set(qualifying):
        problems.append(SCOPE_MISMATCH)
    if set(view.game_ids) != {row.game_id for row in observed}:
        problems.append(SCOPE_MISMATCH)
    if not counts_as(view.sample_size, len(qualifying)) or not counts_as(
        view.denominator, len(observed)
    ):
        problems.append(POPULATION_MISMATCH)
    if not same(view.value, float(len(qualifying)), tolerance(view.decimals)):
        problems.append(ARITHMETIC_MISMATCH)
    if problems:
        return invalid(problems, "player_threshold_count")
    return Proof("verified", "player_threshold_count")


def _team_accepts(subject: str, comparator: str, cutoff: float, own: float, other: float) -> bool:
    """One game against one cutoff, with the outcome-gated margin and deficit subjects."""
    if subject == "own_points":
        measured = own
    elif subject == "opponent_points":
        measured = other
    elif subject == "margin":
        if own <= other:
            return False
        measured = own - other
    else:
        if other <= own:
            return False
        measured = other - own
    return COMPARATORS[comparator](measured, cutoff)
