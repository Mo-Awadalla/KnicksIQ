"""Window deltas: current window against a baseline or the latest appearances.

Two shapes reach here. An appearance delta splits one subject's observed appearances
into the declared recent count and the prior remainder, both of which must clear the
release appearance minimum. A window delta names its current and baseline game sets
outright, which must not overlap and must both be covered by the citation.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_box import aggregate
from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    EXPANSION_MISMATCH,
    MINIMUM_APPEARANCES,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SCOPE_MISMATCH,
    SUBJECT_MISMATCH,
    WINDOW_UNVERIFIED,
    ClaimView,
    Population,
    Proof,
    blocked,
    counts_as,
    declared_ids,
    invalid,
    player_of,
    policy_problems,
    population_invalid,
    same,
    tolerance,
)
from app.evaluation.arithmetic_window import recent_window

DELTA_SUFFIX = ":delta"


def prove(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof | None:
    """One delta recipe, or None when this claim is not one."""
    if not view.metric.endswith(DELTA_SUFFIX):
        return None
    return _delta(view, rows, population)


def _delta(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    window = view.window
    if not isinstance(window, dict):
        return blocked(WINDOW_UNVERIFIED)
    if "current" in window and "baseline" in window:
        return _window_delta(view, rows, population)
    if window.get("kind") == "last_n" and window.get("unit") == "appearances":
        return _appearance_delta(view, rows, population)
    return blocked(WINDOW_UNVERIFIED)


def _appearance_delta(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    window = view.window or {}
    if view.sample_size is None or view.denominator is None:
        return blocked(POPULATION_UNVERIFIED)
    recent_count, problems, reason = recent_window(view, window)
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems)
    policy, reason = policy_problems(view.eligibility)
    if reason:
        return blocked(reason)
    if policy:
        return invalid(policy)
    subject = player_of(view.subject)
    if subject is None:
        return invalid((SUBJECT_MISMATCH,))
    missing = population.gap(box=True)
    if missing:
        return blocked(missing)
    appearances = population.appearances(subject)
    if appearances is None:
        return blocked(POPULATION_UNVERIFIED)
    if len(appearances) < recent_count:
        return invalid((POPULATION_MISMATCH,), "appearance_delta")
    recent = appearances[-recent_count:]
    prior = appearances[:-recent_count]
    if len(recent) < MINIMUM_APPEARANCES or len(prior) < MINIMUM_APPEARANCES:
        return invalid((POPULATION_MISMATCH,), "appearance_delta")
    stat = view.metric[: -len(DELTA_SUFFIX)]
    recent_value, reason = aggregate([row.row for row in recent], stat)
    if reason:
        return blocked(reason)
    prior_value, prior_reason = aggregate([row.row for row in prior], stat)
    if prior_reason:
        return blocked(prior_reason)
    if recent_value is None or prior_value is None:
        return invalid((ARITHMETIC_MISMATCH,), "appearance_delta")
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    story = [row.game_id for row in appearances]
    problems: list[str] = []
    if not same(view.value, recent_value - prior_value, tolerance(view.decimals)):
        problems.append(ARITHMETIC_MISMATCH)
    if not counts_as(view.sample_size, len(recent)) or not counts_as(view.denominator, len(recent)):
        problems.append(POPULATION_MISMATCH)
    if list(cited) != story or list(view.game_ids) != story:
        problems.append(SCOPE_MISMATCH)
    if problems:
        return population_invalid(problems, "appearance_delta")
    return Proof("verified", "appearance_delta", population_cited=True)


def _window_delta(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    window = view.window or {}
    if view.sample_size is None:
        return blocked(POPULATION_UNVERIFIED)
    current = declared_ids(window.get("current"))
    baseline = declared_ids(window.get("baseline"))
    if not current or not baseline:
        return blocked(WINDOW_UNVERIFIED)
    subject = player_of(view.subject)
    if subject is None:
        return invalid((SUBJECT_MISMATCH,))
    missing = population.gap(box=True)
    if missing:
        return blocked(missing)
    if set(current) & set(baseline):
        return invalid((SCOPE_MISMATCH,), "window_delta")
    current_rows = population.appearances(subject, current)
    baseline_rows = population.appearances(subject, baseline)
    if current_rows is None or baseline_rows is None:
        return blocked(POPULATION_UNVERIFIED)
    if {row.game_id for row in current_rows} != set(current) or {
        row.game_id for row in baseline_rows
    } != set(baseline):
        return invalid((SCOPE_MISMATCH,), "window_delta")
    mean = view.denominator is not None
    stat = view.metric[: -len(DELTA_SUFFIX)]
    current_value, reason = aggregate([row.row for row in current_rows], stat, mean=mean)
    if reason:
        return blocked(reason)
    baseline_value, baseline_reason = aggregate([row.row for row in baseline_rows], stat, mean=mean)
    if baseline_reason:
        return blocked(baseline_reason)
    if current_value is None or baseline_value is None:
        return invalid((ARITHMETIC_MISMATCH,), "window_delta")
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    problems: list[str] = []
    if not same(view.value, current_value - baseline_value, tolerance(view.decimals)):
        problems.append(ARITHMETIC_MISMATCH)
    if not counts_as(view.sample_size, len(current_rows)):
        problems.append(POPULATION_MISMATCH)
    if mean and not counts_as(view.denominator, len(current_rows)):
        problems.append(POPULATION_MISMATCH)
    if set(cited) != set(current) | set(baseline):
        problems.append(EXPANSION_MISMATCH)
    if not set(current) | set(baseline) <= set(view.game_ids):
        problems.append(SCOPE_MISMATCH)
    if problems:
        return population_invalid(problems, "window_delta")
    return Proof("verified", "window_delta", population_cited=True)
