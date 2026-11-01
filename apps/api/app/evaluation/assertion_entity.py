"""The subject one canonical fact declares, against the subject an answer delivered.

A fact names its identity in one of three ways: an explicit ``subject``, a
``player_name``, or a structured value that carries its player's name alongside the
number. Each is an identity the mapping can verify, so a delivery that substituted
another player, another id shape or no subject at all is a mismatch rather than an
acceptable restatement. A fact that declares no subject belongs to no subject this
check can hold an answer to, so it fails closed.

The module is a leaf of the assertion checks: it reports through their shared result
vocabulary and never imports the checks that call it.
"""

from __future__ import annotations

from app.evaluation.assertion_results import AssertionFailure
from app.evaluation.assertion_vocabulary import DICT_METRICS
from app.evaluation.labels import CanonicalFact
from app.evaluation.mapping import RuntimeMapping
from app.evaluation.observations import TypedClaim


def declared_player_name(fact: CanonicalFact) -> str | None:
    """The player identity a fact declares, explicitly or inside its structured value.

    A leaderboard fact names its player in the value it asserts (``name`` alongside the
    measured total), which is a player identity the mapping can verify just as a
    top-level ``player_name`` can.
    """
    if fact.player_name:
        return fact.player_name
    value = fact.value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name.strip():
            return name
    return None


def player_identity_failure(
    name: str, claim: TypedClaim, mapping: RuntimeMapping
) -> AssertionFailure | None:
    """The delivered subject is that player, a different player, or unplaceable at all.

    A subject the mapping cannot resolve is unverifiable rather than wrong, so a mapping
    that does not carry the player blocks the identity instead of asserting a mismatch.
    """
    subject = (claim.subject_id or "").strip()
    if not subject.startswith("player:") or not subject.split(":", 1)[1].isdigit():
        return AssertionFailure("entity_mismatch", f"{name} -> {subject or 'no subject'}")
    delivered = mapping.player_name(int(subject.split(":", 1)[1]))
    if delivered is None:
        return AssertionFailure("subject_unverifiable", f"{name} -> {subject}")
    if delivered.casefold() != name.casefold():
        return AssertionFailure("entity_mismatch", f"{name} -> {delivered}")
    return None


def subject_failures(
    fact: CanonicalFact, claim: TypedClaim, mapping: RuntimeMapping
) -> list[AssertionFailure]:
    """The canonical subject the fact declares must be the subject the answer delivered.

    An explicit ``subject`` is the fact's whole identity. A ``player_name``, or a
    structured value that names its player, is a player identity verified through the
    mapping. A fact that declares neither belongs to no subject this check can hold the
    answer to, so it fails closed instead of accepting any subject.
    """
    declared = declared_player_name(fact)
    if fact.subject:
        delivered = (claim.subject_id or "").strip()
        if delivered.casefold() != fact.subject.casefold():
            return [
                AssertionFailure(
                    "entity_mismatch", f"{fact.subject} -> {delivered or 'no subject'}"
                )
            ]
        if declared:
            failure = player_identity_failure(declared, claim, mapping)
            return [failure] if failure else []
        return []
    if declared:
        failure = player_identity_failure(declared, claim, mapping)
        return [failure] if failure else []
    if (
        fact.metric in DICT_METRICS
        and isinstance(fact.value, dict)
        and fact.value.get("nba_game_id")
    ):
        # A game fact's identity is the game its own value names, and the delivered claim
        # must map to that same game, which the evidence check enforces.
        return []
    return [AssertionFailure("subject_unverifiable", fact.metric)]
