"""Typed fact checks: value and type, unit, scope, entity, evidence and display.

Each check compares typed fields only. Delivered prose is used just to prove a
claim was displayed and that no number was left unattributed. The scope invariants
and the projected game subject live in ``assertion_scope``, the game-count
projection in ``assertion_games``, and the result record in ``assertion_results``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.evaluation.assertion_entity import subject_failures
from app.evaluation.assertion_games import projected_count_failures
from app.evaluation.assertion_results import AssertionFailure, FactCheck
from app.evaluation.assertion_scope import ProjectedGame, own_team, scope_failures
from app.evaluation.assertion_vocabulary import (
    DICT_METRICS,
    METRIC_ALIASES,
    metric_key,
    parse_scope,
)
from app.evaluation.labels import CanonicalFact
from app.evaluation.mapping import RuntimeMapping
from app.evaluation.observations import (
    Observation,
    TypedClaim,
    canonical_digest,
)

_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])")
_SEASON = re.compile(r"\b20\d{2}-\d{2}\b")
_ISO_DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def numeric_tokens(text: str) -> list[Decimal]:
    """Numbers asserted in delivered prose, excluding dates, seasons and bare years.

    A whole ISO date is removed before seasons and years are, because a season pattern
    would otherwise eat its first two segments and leave the day behind as an asserted
    number.
    """
    scrubbed = _ISO_DATE.sub(" ", text)
    scrubbed = _SEASON.sub(" ", scrubbed)
    scrubbed = _YEAR.sub(" ", scrubbed)
    values: list[Decimal] = []
    for match in _NUMBER.finditer(scrubbed):
        raw = match.group(1).replace(",", "")
        try:
            values.append(Decimal(raw))
        except InvalidOperation:
            continue
    return values


def _decimals(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _claim_matches_metric(claim: TypedClaim, fact: CanonicalFact) -> bool:
    if fact.metric in DICT_METRICS:
        # A structured fact is matched only by the claim that declares the same metric.
        # Its value is then compared field by field; another dict claim is not it.
        return isinstance(claim.value, dict) and metric_key(claim.metric_id) == metric_key(
            fact.metric
        )
    alias = METRIC_ALIASES.get(metric_key(fact.metric))
    if alias is None:
        return False
    return any(tokens == claim.metric_tokens for tokens in alias.tokens)


def _display_precision(value: Any, tokens: list[Decimal]) -> int | None:
    """Decimals used where the claim's own value was displayed, if it was displayed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    target = Decimal(str(value))
    for token in tokens:
        tolerance = Decimal(1).scaleb(-_decimals(token)) / 2 + Decimal("1e-9")
        if abs(token - target) <= tolerance:
            return _decimals(token)
    return None


def _values_match(expected: Any, actual: Any, precision: int | None = None) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, int):
        return isinstance(actual, int) and actual == expected
    if isinstance(expected, float):
        if not isinstance(actual, (int, float)):
            return False
        if precision is not None:
            # The answer may state the canonical value at the precision it displayed.
            return round(float(expected), precision) == round(float(actual), precision)
        tolerance = max(Decimal(1).scaleb(-_decimals(Decimal(str(expected)))) / 2, Decimal("1e-9"))
        return abs(Decimal(str(actual)) - Decimal(str(expected))) <= tolerance
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            return False
        return all(_values_match(value, actual[key]) for key, value in expected.items())
    return expected == actual


LOSS_MARGIN_OPERATIONS = frozenset({"largest_loss_margin"})


def _projected_value(claim: TypedClaim) -> Any:
    """The claim's value as the canonical metric states it, for one explicit projection.

    A largest-loss ranking records its own deficit as a nonnegative magnitude under its
    loss metric. The sign is projected only when the claim itself names that loss
    operation, so an unlabelled or differently attributed claim keeps its own value and
    never matches a negative margin. Nothing is projected onto the fact's value, so a
    win margin is never read as the absolute size of a loss.
    """
    if claim.metric_tokens != frozenset({"loss", "margin"}):
        return claim.value
    operation = str((claim.eligibility or {}).get("operation") or "")
    value = claim.value
    if (
        operation in LOSS_MARGIN_OPERATIONS
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and value >= 0
    ):
        return -value
    return value


def _claim_units(claim: TypedClaim, fact: CanonicalFact) -> bool:
    alias = METRIC_ALIASES.get(metric_key(fact.metric))
    if alias is None or fact.metric in DICT_METRICS:
        return True
    unit = (claim.unit or "").strip().casefold()
    return unit in {value.casefold() for value in alias.units}


_REFERENCE_SEGMENTS = {"game": 2, "box": 3, "team_box": 3, "period": 4}


def _reference_games(reference: str) -> set[str]:
    """Expand one canonical evidence reference to the canonical game ids it covers.

    Every canonical source prefix names the NBA game id in its second segment: a game,
    a player box row, a team box row or a period score. An unapproved prefix, an empty
    segment or a segment count that prefix never emits is unexpressible, not guessed.
    """
    parts = reference.split(":")
    expected = _REFERENCE_SEGMENTS.get(parts[0])
    if expected is None or len(parts) != expected or not all(parts):
        raise ValueError(reference)
    return {f"game:{parts[1]}"}


def _evidence_failures(
    fact: CanonicalFact, claim: TypedClaim, mapping: RuntimeMapping
) -> list[AssertionFailure]:
    """The approved population is expanded from every canonical source reference."""
    if not fact.canonical_evidence_ids:
        return [AssertionFailure("evidence_scope_mismatch", "label names no evidence")]
    expected: set[str] = set()
    try:
        for reference in fact.canonical_evidence_ids:
            expected.update(_reference_games(reference))
    except ValueError as exc:
        return [AssertionFailure("evidence_scope_mismatch", f"unexpressible {exc}")]
    if not claim.game_ids:
        return [AssertionFailure("evidence_scope_mismatch", "claim has no game ids")]
    mapped = [mapping.canonical_for_game(game) for game in claim.game_ids]
    if any(item is None for item in mapped):
        return [AssertionFailure("evidence_unmapped", "claim game id not in mapping")]
    if set(mapped) != expected:
        return [AssertionFailure("evidence_scope_mismatch", "claim game set differs")]
    return []


def _season_failures(claim: TypedClaim, observation: Observation) -> list[AssertionFailure]:
    expected = str(observation.request.get("season") or "")
    if not expected:
        return [AssertionFailure("season_unverifiable", "request carries no season")]
    if claim.season != expected:
        return [AssertionFailure("season_mismatch", f"{claim.season} != {expected}")]
    return []


def _numeric_leaves(value: Any) -> list[Decimal]:
    """Numbers contained in a typed value, including dict fields of scoreline facts."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [Decimal(str(value))]
    if isinstance(value, dict):
        leaves: list[Decimal] = []
        for item in value.values():
            leaves.extend(_numeric_leaves(item))
        return leaves
    return []


_IDENTITY_FIELDS = frozenset({"nba_game_id", "nba_player_id"})


def _asserted_numbers(value: Any) -> list[Decimal]:
    """The numbers a delivered value asserts, excluding the identities it carries."""
    if isinstance(value, dict):
        return [
            leaf
            for key, item in value.items()
            if key not in _IDENTITY_FIELDS
            for leaf in _numeric_leaves(item)
        ]
    return _numeric_leaves(value)


def _display_failures(claim: TypedClaim, tokens: list[Decimal]) -> list[AssertionFailure]:
    """Every number the delivered value asserts must have been stated in the answer."""
    value = claim.value
    if isinstance(value, dict):
        asserted = _asserted_numbers(value)
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    else:
        asserted = [Decimal(str(value))]
    for leaf in asserted:
        if not _token_displays(leaf, tokens):
            return [AssertionFailure("claim_not_displayed", str(leaf))]
    return []


def _token_displays(value: Decimal, tokens: list[Decimal]) -> bool:
    """A listed token states the value, at the precision the token itself displayed."""
    target = abs(value)
    for token in tokens:
        tolerance = Decimal(1).scaleb(-_decimals(token)) / 2 + Decimal("1e-9")
        if abs(abs(token) - target) <= tolerance:
            return True
    return False


def fact_failures(
    fact: CanonicalFact,
    claim: TypedClaim,
    observation: Observation,
    mapping: RuntimeMapping,
    tokens: list[Decimal],
) -> list[AssertionFailure]:
    """Every reason this claim fails to be the approved fact. Empty means it matches.

    A canonical id inside an asserted value is compared as that canonical id. The
    mapping proves which row a reference names; it never rewrites the fact into the
    runtime's own ids, so a delivery that substituted a SQL id for an NBA id fails.
    """
    failures: list[AssertionFailure] = []
    precision = _display_precision(claim.value, tokens)
    if claim.release_id != mapping.version:
        failures.append(AssertionFailure("release_mismatch", claim.release_id))
    if not _values_match(fact.value, _projected_value(claim), precision):
        failures.append(AssertionFailure("numeric_mismatch", str(claim.value)))
    if not _claim_units(claim, fact):
        failures.append(AssertionFailure("unit_mismatch", str(claim.unit)))
    if fact.denominator is not None and (
        claim.denominator is None or float(claim.denominator) != fact.denominator
    ):
        failures.append(
            AssertionFailure("denominator_mismatch", f"denominator {claim.denominator}")
        )
    if fact.appearances is not None and claim.sample_size != fact.appearances:
        failures.append(
            AssertionFailure("denominator_mismatch", f"appearances {claim.sample_size}")
        )
    failures.extend(scope_failures(parse_scope(fact.scope), claim))
    failures.extend(subject_failures(fact, claim, mapping))
    failures.extend(_evidence_failures(fact, claim, mapping))
    failures.extend(_season_failures(claim, observation))
    failures.extend(_display_failures(claim, tokens))
    return failures


SCORELINE_FIELDS = (
    "nba_game_id",
    "home_team_id",
    "away_team_id",
    "home_score",
    "away_score",
    "game_date",
)


def _indexed(failures: list[AssertionFailure], index: int) -> list[AssertionFailure]:
    return [AssertionFailure(item.code, item.detail, index) for item in failures]


def _scoreline_failures(
    fact: CanonicalFact,
    observation: Observation,
    mapping: RuntimeMapping,
    tokens: list[Decimal],
) -> list[AssertionFailure]:
    """Project a canonical game score through the receipt that actually proves it.

    A delivered margin or extreme claim is still delivered evidence about one game.
    The projection is credited only when that game's own receipt snapshot rehashes to
    the immutable mapped row, the claim is about that same game, and the answer states
    both scores. It answers to the same scope, window, denominator, release and season
    invariants as a typed fact, so an unrecognised or unprovable scope fails closed
    instead of passing through the projected receipt. A claimed digest, an unverified
    snapshot or an undisplayed scoreline never stands in for the fact.
    """
    scope = parse_scope(fact.scope)
    if not scope.parseable:
        return [AssertionFailure("scope_not_expressible", scope.raw, fact.index)]
    expected_games: set[str] = set()
    try:
        for reference in fact.canonical_evidence_ids:
            expected_games.update(_reference_games(reference))
    except ValueError as exc:
        return [AssertionFailure("evidence_scope_mismatch", f"unexpressible {exc}", fact.index)]
    if len(expected_games) != 1:
        return [AssertionFailure("evidence_scope_mismatch", "one game per scoreline", fact.index)]
    canonical = next(iter(expected_games))
    row = mapping.rows.get(canonical)
    runtime_game = mapping.runtime_for_canonical_game(canonical.split(":", 1)[1])
    if row is None or runtime_game is None:
        return [AssertionFailure("evidence_unmapped", canonical, fact.index)]
    if not isinstance(fact.value, dict) or set(fact.value) != set(SCORELINE_FIELDS):
        return [AssertionFailure("scope_not_expressible", "scoreline keys", fact.index)]
    for claim in observation.claims:
        if runtime_game not in claim.game_ids:
            continue
        for reference in claim.supporting_evidence_ids:
            record = observation.evidence.get(reference)
            if record is None or record.source_row is None:
                continue
            if record.row_sha256 != row.row_sha256:
                continue
            if canonical_digest(record.source_row) != row.row_sha256:
                continue
            projection = {key: record.source_row.get(key) for key in SCORELINE_FIELDS}
            failures: list[AssertionFailure] = []
            if claim.release_id != mapping.version:
                failures.append(AssertionFailure("release_mismatch", claim.release_id, fact.index))
            if not _values_match(fact.value, projection):
                failures.append(AssertionFailure("numeric_mismatch", str(projection), fact.index))
            if fact.denominator is not None or fact.appearances is not None:
                # A scoreline is one game's identity, so it carries no denominator.
                failures.append(
                    AssertionFailure(
                        "denominator_mismatch", "a scoreline carries no denominator", fact.index
                    )
                )
            failures.extend(
                _indexed(
                    scope_failures(scope, ProjectedGame.of(projection, own_team(fact))),
                    fact.index,
                )
            )
            failures.extend(_indexed(_season_failures(claim, observation), fact.index))
            for score in (projection["home_score"], projection["away_score"]):
                if not any(abs(token - Decimal(str(score))) <= Decimal("1e-9") for token in tokens):
                    failures.append(AssertionFailure("claim_not_displayed", str(score), fact.index))
            return failures
    return [AssertionFailure("scoreline_evidence_unverified", canonical, fact.index)]


def check_fact(
    fact: CanonicalFact,
    observation: Observation,
    mapping: RuntimeMapping,
    tokens: list[Decimal],
) -> FactCheck:
    candidates = [claim for claim in observation.claims if _claim_matches_metric(claim, fact)]
    if not candidates:
        counted = projected_count_failures(fact, observation, mapping)
        if counted is not None:
            if not counted and not _token_displays(Decimal(str(fact.value)), tokens):
                # A count the record supports is still a fact the answer must state.
                counted = [AssertionFailure("claim_not_displayed", str(fact.value), fact.index)]
            return FactCheck(fact.index, None, tuple(counted))
        if fact.metric in DICT_METRICS:
            projected = _scoreline_failures(fact, observation, mapping, tokens)
            return FactCheck(fact.index, None, tuple(projected))
        return FactCheck(
            fact.index,
            None,
            (AssertionFailure("no_typed_claim_for_fact", fact.metric, fact.index),),
        )
    failures: list[AssertionFailure] = []
    matched: TypedClaim | None = None
    for claim in candidates:
        candidate_failures = fact_failures(fact, claim, observation, mapping, tokens)
        if not candidate_failures:
            return FactCheck(fact.index, claim.claim_id)
        if matched is None or len(candidate_failures) < len(failures):
            matched, failures = claim, candidate_failures
    return FactCheck(fact.index, matched.claim_id if matched else None, tuple(failures))
