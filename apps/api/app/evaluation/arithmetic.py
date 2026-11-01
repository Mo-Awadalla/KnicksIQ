"""Independent arithmetic for emitted analyst metrics over verified row snapshots.

A recorded numerator, ingredient or denominator is never proof: the formula is
recomputed from the verified rows. An unprovable recipe blocks instead of crediting.

The module is a dispatcher. Team-game, box-score and whole-population recipes live in
their own modules so each formula can be read beside the claim shape it proves.
"""

from __future__ import annotations

from typing import Any

from app.evaluation import arithmetic_advanced, arithmetic_box, arithmetic_game, arithmetic_window
from app.evaluation.arithmetic_core import (
    EXPANSION_MISMATCH,
    GAME,
    PERIOD,
    PLAYER,
    UNSUPPORTED,
    ClaimView,
    Population,
    PopulationRow,
    Proof,
    aggregation_suffix,
    blocked,
    invalid,
    tolerance,
)

__all__ = [
    "ClaimView",
    "Population",
    "PopulationRow",
    "Proof",
    "prove",
    "recipe_family",
    "tolerance",
]


def recipe_family(metric: str) -> str | None:
    """Which module's formulas own one metric id, before any whole-population recipe."""
    if metric in arithmetic_game.GAME_METRICS or metric == arithmetic_game.GAME_SCORE:
        return "game"
    if metric == arithmetic_game.BENCH_POINTS:
        return "bench"
    if metric == "period:points":
        return "period"
    if metric.endswith(arithmetic_box.STATLINE_SUFFIX):
        return (
            "box"
            if arithmetic_box.box_column(metric[: -len(arithmetic_box.STATLINE_SUFFIX)])
            else None
        )
    base, aggregation = aggregation_suffix(metric)
    if base in arithmetic_box.RATE_STATS or base in arithmetic_box.DERIVED_STATS:
        return "box"
    if base in arithmetic_box.COUNTED_STATS:
        return "box"
    if aggregation in {"total", "average"} and arithmetic_box.box_column(base) is not None:
        return "box"
    return None


def prove(
    view: ClaimView,
    *,
    rows: list[dict[str, Any]],
    collections: list[str],
    player: str | None,
    population: Population | None = None,
) -> Proof:
    """Prove one claim from its cited snapshots and, when needed, the whole population."""
    if not rows or len(collections) != len(rows):
        return blocked(UNSUPPORTED)
    oracle = population if population is not None else Population()
    direct = arithmetic_advanced.prove_direct(view, rows, oracle)
    if direct is not None:
        return direct
    membership = arithmetic_window.check_window_membership(view, rows, oracle)
    if membership is not None:
        if membership.reason:
            return blocked(membership.reason)
        if membership.problems:
            return invalid(membership.problems)
    return _cited(view, rows, collections, player)


def _cited(
    view: ClaimView, rows: list[dict[str, Any]], collections: list[str], player: str | None
) -> Proof:
    """A recipe provable from the cited rows alone."""
    family = recipe_family(view.metric)
    kinds = set(collections)
    if family == "game":
        if kinds != {GAME}:
            return invalid((EXPANSION_MISMATCH,))
        return arithmetic_game.prove_game(view, rows, collections)
    if family == "box":
        return arithmetic_box.prove_box(view, rows, collections, player)
    if family == "period":
        if kinds != {PERIOD}:
            return invalid((EXPANSION_MISMATCH,))
        return arithmetic_game.prove_period(view, rows)
    if family == "bench":
        if not (GAME in kinds and kinds <= {GAME, PLAYER}):
            return invalid((EXPANSION_MISMATCH,))
        return arithmetic_game.prove_bench(view, rows, collections)
    return blocked(UNSUPPORTED)
