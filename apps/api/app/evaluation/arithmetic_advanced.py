"""Whole-population recipes: dispatch one claim to the family module that owns it.

Each of these claims cites the population it counted and is attributed to a subset of
it: the matching games, the tied runs, the latest appearances, the subject's own
appearances or the qualifiers. The citations are proved elsewhere as receipts. The
numbers here are recomputed from the mapping's verified projection of the whole
release, so no claim can earn credit by citing only the part of the population that
makes its own arithmetic true.

A recipe that cannot be recomputed because the population snapshot or the claim's own
policy record is missing blocks instead of falling back to the subset the answer chose.

The families live beside this file — ``arithmetic_threshold``, ``arithmetic_streak``,
``arithmetic_delta`` and ``arithmetic_rank`` — and each one answers only for its own
claim shape, so this module stays the single ordered dispatch over them.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_core import ClaimView, Population, Proof
from app.evaluation.arithmetic_delta import prove as prove_delta
from app.evaluation.arithmetic_rank import prove as prove_rank
from app.evaluation.arithmetic_streak import prove as prove_streak
from app.evaluation.arithmetic_threshold import prove as prove_threshold

POPULATION_RECIPES = (prove_threshold, prove_streak, prove_delta, prove_rank)


def prove_direct(
    view: ClaimView, rows: list[dict[str, Any]], population: Population
) -> Proof | None:
    """A whole-population recipe, or None when this claim is not one of them."""
    for recipe in POPULATION_RECIPES:
        proof = recipe(view, rows, population)
        if proof is not None:
            return proof
    return None
