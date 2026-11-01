"""Project a game count from the typed record that states its own population.

A record answer delivers wins and losses together with the number of games they were
counted over. That recorded population is the count itself, so a labelled ``games``
fact is satisfied by the record's own sample or considered population instead of
demanding a claim the producer never issues.

The projection stays strict. The count must equal the recorded sample, any recorded
considered population must agree with it, every considered game id must name a game the
mapping carries, and the record must cite at least one receipt. A count the record does
not support is a denominator mismatch, never an invented number.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.assertion_results import AssertionFailure
from app.evaluation.assertion_scope import scope_failures
from app.evaluation.assertion_vocabulary import metric_key, parse_scope
from app.evaluation.labels import CanonicalFact
from app.evaluation.mapping import RuntimeMapping
from app.evaluation.observations import Observation, TypedClaim

RECORD_METRICS = frozenset({"wins", "losses"})
COUNT_METRICS = frozenset({"games", "game_count"})


def projected_count_failures(
    fact: CanonicalFact, observation: Observation, mapping: RuntimeMapping
) -> list[AssertionFailure] | None:
    """The verdict for a game-count fact, or None when this fact is not a game count."""
    if metric_key(fact.metric) not in COUNT_METRICS:
        return None
    expected = fact.value
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        return [
            AssertionFailure(
                "scope_not_expressible", "a game count is not a whole number", fact.index
            )
        ]
    scope = parse_scope(fact.scope)
    counted = False
    scope_problems: list[AssertionFailure] = []
    for claim in observation.claims:
        if metric_key(claim.metric_id) not in RECORD_METRICS:
            continue
        if not (claim.subject_id or "").startswith("team:"):
            continue
        population = _population(claim, mapping)
        if population is None:
            continue
        counted = True
        if population != expected:
            continue
        problems = scope_failures(scope, claim)
        if not problems:
            return []
        scope_problems.extend(problems)
    # An unparseable or unsatisfied scope is the reason the count is not proven, so it
    # is reported as such rather than as a count the record never reached.
    if scope_problems:
        return [
            AssertionFailure(code, detail, fact.index)
            for code, detail in dict.fromkeys((item.code, item.detail) for item in scope_problems)
        ]
    if counted:
        return [AssertionFailure("denominator_mismatch", f"games {expected}", fact.index)]
    return [AssertionFailure("no_typed_claim_for_fact", fact.metric, fact.index)]


def _population(claim: TypedClaim, mapping: RuntimeMapping) -> int | None:
    """The games a record says it counted, validated against the mapping when it names them."""
    if not claim.supporting_evidence_ids:
        return None
    eligibility: dict[str, Any] = claim.eligibility or {}
    stated = [
        value
        for value in (claim.sample_size, eligibility.get("considered_games"))
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    if not stated or any(value != stated[0] for value in stated):
        return None
    counted = stated[0]
    considered = eligibility.get("considered_game_ids") or []
    if considered:
        if len({str(item) for item in considered}) != counted:
            return None
        for item in considered:
            try:
                if mapping.canonical_for_game(item) is None:
                    return None
            except (TypeError, ValueError):
                return None
    return counted
