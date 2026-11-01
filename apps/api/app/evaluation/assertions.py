"""Case-level assertion suites over one recorded observation.

These check delivered claims against approved facts and their literal score components,
every number in the prose, every named entity, and the ranked retrieval trace.
Acceptance reuses the same complete
canonical comparison as ``check_fact`` — metric, value at displayed precision,
unit, subject, scope, window, denominator, release, population and season — so an
additions-only predicate can never be weaker than the fact check.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.evaluation.assertion_checks import (
    AssertionFailure,
    _claim_matches_metric,
    _decimals,
    _numeric_leaves,
    fact_failures,
    numeric_tokens,
)
from app.evaluation.assertion_entity import declared_player_name
from app.evaluation.labels import CanonicalFact, ExpectationCase
from app.evaluation.mapping import RuntimeMapping
from app.evaluation.observations import Observation, TypedClaim, canonical_digest


def _score_component(fact: CanonicalFact, claim: TypedClaim) -> CanonicalFact | None:
    if fact.metric != "game_score" or not isinstance(fact.value, dict) or claim.unit != "points":
        return None
    if claim.metric_id not in {"points", "opponent_points"}:
        return None
    team = (claim.subject_id or "").removeprefix("team:")
    if team not in {fact.value.get("home_team_id"), fact.value.get("away_team_id")}:
        return None
    home = team == fact.value.get("home_team_id")
    if claim.metric_id == "opponent_points":
        home = not home
    value = fact.value.get("home_score" if home else "away_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return replace(fact, metric=claim.metric_id, value=value)


def extra_claims(
    case: ExpectationCase, observation: Observation, mapping: RuntimeMapping
) -> list[AssertionFailure]:
    """Every claim must match an approved fact or its literal score component."""
    tokens = numeric_tokens(observation.answer)
    accepted: set[str] = set()
    for claim in observation.claims:
        for fact in case.facts:
            candidate = (
                fact if _claim_matches_metric(claim, fact) else _score_component(fact, claim)
            )
            if candidate is None:
                continue
            if not fact_failures(candidate, claim, observation, mapping, tokens):
                accepted.add(claim.claim_id)
                break
    return [
        AssertionFailure("unsupported_additional_fact", claim.metric_id)
        for claim in observation.claims
        if claim.claim_id not in accepted
    ]


def _attributed(token: Decimal, allowed: set[Decimal]) -> bool:
    """A listed number may appear rounded to the precision it was displayed at."""
    tolerance = Decimal(1).scaleb(-_decimals(token)) / 2 + Decimal("1e-9")
    for value in allowed:
        if abs(token - value) <= tolerance or abs(token + value) <= tolerance:
            return True
    return False


def unattributed_numbers(case: ExpectationCase, observation: Observation) -> list[AssertionFailure]:
    """Numbers in the delivered answer must belong to a delivered claim or expected fact.

    The permitted numbers are typed or immutable: a claim's own value, sample and
    denominator, the population its record states it considered, the numerator and
    denominator its own receipts record, a fact's value, denominator and appearances,
    and the numbers the frozen question itself states as its criterion. Nothing widens
    the allowance to the answer's own prose.
    """
    allowed: set[Decimal] = set()
    for claim in observation.claims:
        game_ids = claim.game_ids or ()
        allowed.update(_numeric_leaves(claim.value))
        for value in (claim.denominator, claim.sample_size):
            allowed.update(_numeric_leaves(value))
        eligibility = claim.eligibility or {}
        allowed.update(_numeric_leaves(eligibility.get("considered_games")))
        considered = eligibility.get("considered_game_ids") or []
        if considered:
            allowed.add(Decimal(len(considered)))
        for reference in claim.supporting_evidence_ids:
            record = observation.evidence.get(reference)
            if record is None:
                continue
            for value in (
                record.numerator,
                record.denominator,
                record.sample_size,
                record.made,
                record.attempted,
            ):
                allowed.update(_numeric_leaves(value))
            if (
                len(game_ids) == 1
                and reference == f"{claim.release_id}:game:{game_ids[0]}"
                and record.release_id == claim.release_id
                and record.source_row is not None
                and record.row_sha256 is not None
                and canonical_digest(record.source_row) == record.row_sha256
            ):
                for field in ("home_score", "away_score"):
                    allowed.update(_numeric_leaves(record.source_row.get(field)))
    for fact in case.facts:
        allowed.update(_numeric_leaves(fact.value))
        allowed.update(_numeric_leaves(fact.numerator))
        if fact.denominator is not None:
            allowed.add(Decimal(str(fact.denominator)).normalize())
        if fact.appearances is not None:
            allowed.add(Decimal(str(fact.appearances)).normalize())
    allowed.update(numeric_tokens(case.question))
    failures: list[AssertionFailure] = []
    for token in numeric_tokens(observation.answer):
        # Attribution is sign-insensitive; the sign itself is asserted by the typed value check.
        if _attributed(token, allowed):
            continue
        failures.append(AssertionFailure("unattributed_numeric", str(token)))
    return failures


def entity_assertions(
    case: ExpectationCase, observation: Observation, mapping: RuntimeMapping
) -> list[AssertionFailure]:
    """Every subject or player named by an expected fact must be a delivered subject."""
    failures: list[AssertionFailure] = []
    named = {name for fact in case.facts if (name := declared_player_name(fact))}
    subjects = {fact.subject for fact in case.facts if fact.subject}
    delivered_subjects = {(claim.subject_id or "").casefold() for claim in observation.claims}
    for subject in sorted(subjects):
        if subject.casefold() not in delivered_subjects:
            failures.append(AssertionFailure("entity_mismatch", subject))
    if not named:
        return failures
    delivered: set[str] = set()
    for claim in observation.claims:
        subject = claim.subject_id or ""
        if subject.startswith("player:") and subject.split(":", 1)[1].isdigit():
            name = mapping.player_name(int(subject.split(":", 1)[1]))
            if name:
                delivered.add(name.casefold())
    for name in sorted(named):
        if name.casefold() not in delivered:
            failures.append(AssertionFailure("entity_mismatch", name))
    return failures


def trace_first_ids(observation: Observation, name: str, limit: int) -> tuple[str, ...]:
    """First ``limit`` candidate keys of the request's own ranked trace."""
    for entry in reversed(observation.traces):
        items = getattr(entry, name)
        if items:
            return tuple(item.evidence_id for item in items[:limit])
    return ()
