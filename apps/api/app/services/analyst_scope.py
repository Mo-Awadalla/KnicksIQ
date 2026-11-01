"""Follow-up scope inheritance from verified server state.

A follow-up may reuse the scope the server committed earlier: players, phase, opponent,
home/away, result, game IDs, dates, periods and windows. The client transcript is never
authority. A referential ask ("in that game", "that stretch") without a verified anchor
clarifies which game is meant instead of answering a season-wide metric.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.query_operation_decisions import classify_operation
from app.services.query_operations import is_record_request
from app.services.query_resolution import ResolvedQuery

_INHERITED_KEYS = (
    "player_ids",
    "season_type",
    "opponent_id",
    "home_away",
    "game_result",
    "game_ids",
    "date_start",
    "date_end",
    "periods",
    "relative_game_count",
    "relative_game_position",
)

# The keys that name a population rather than qualify one. They are inherited together
# and only when the follow-up does not name a population of its own.
_POPULATION_KEYS = frozenset(
    {
        "game_ids",
        "date_start",
        "date_end",
        "relative_game_count",
        "relative_game_position",
    }
)


def _typed(key: str, value: Any) -> Any:
    """Session scope is stored as JSON; typed fields come back typed."""
    if key in {"date_start", "date_end"} and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _anchored(scope: ResolvedQuery) -> bool:
    return bool(scope.game_ids or (scope.date_start is not None and scope.date_end is not None))


def _names_its_own_population(scope: ResolvedQuery) -> bool:
    """The turn named a new interval or window, so an older game anchor is stale."""
    return (
        scope.date_start is not None
        or scope.date_end is not None
        or bool(scope.relative_game_count)
    )


_ANAPHOR = re.compile(r"\b(he|him|his)\b", re.I)
_NAMED_SUBJECT = re.compile(r"\babout\s+(.+?)[?.!]*$", re.I)
_ARCHIVE_SUBJECT = re.compile(r"\b(knicks|nyk|season|archive|team|playoff|game)\b", re.I)


def prior_scope(
    state: dict[str, Any],
    *,
    version: str,
    rows: list[tuple[PlayerGameStat, Player]],
) -> dict[str, Any]:
    """The committed scope a follow-up may reuse, or nothing.

    A game ID, date, period or window anchor is only authority while the stored release is
    the active release; a different release's games are not the same games. The player
    subject survives a release change because identity is global, and it is kept only when
    that player is actually observed in this release.
    """
    prior = state.get("scope")
    if not isinstance(prior, dict):
        return {}
    if state.get("release") == version:
        return dict(prior)
    observed = {player.id for _, player in rows}
    subject = [pid for pid in prior.get("player_ids") or [] if pid in observed]
    return {"player_ids": subject} if subject else {}


def clarification(
    question: str,
    scope: ResolvedQuery,
    names: list[str],
    *,
    different_player: bool,
) -> ResolvedQuery:
    """Clarify a subject the question never names instead of guessing a player.

    "Interesting stat about X" and a bare pronoun both leave the subject unresolved unless
    the question names the archive itself; a different-player follow-up is asking for a new
    subject, not for the last one to be clarified again.
    """
    if scope.operation_reason is not None:
        return scope
    if scope.player_ids:
        return scope
    subject = _NAMED_SUBJECT.search(question)
    unnamed = (
        subject is not None and not different_player and not _ARCHIVE_SUBJECT.search(subject[1])
    ) or bool(_ANAPHOR.search(question))
    if not unnamed:
        return scope
    return scope.model_copy(
        update={"requires_clarification": True, "clarification_options": list(names)}
    )


def apply_inherited_scope(
    scope: ResolvedQuery,
    prior: dict[str, Any],
    *,
    question: str,
    followup: bool,
    different_player: bool,
    referential: bool,
    games: list[Game],
) -> ResolvedQuery:
    """Fill an unresolved follow-up scope from committed state, then gate references."""
    if scope.operation_reason is not None:
        return scope
    if scope.comparison is None and followup and prior:
        known_games = {game.id for game in games}
        own_population = _names_its_own_population(scope)
        whole_population = bool(
            re.search(r"\b(?:whole|entire|full)\s+(?:season|archive)\b", question, re.I)
        )
        updates = {}
        for key in _INHERITED_KEYS:
            if whole_population and key != "player_ids":
                continue
            if key == "game_result" and is_record_request(question):
                continue
            if own_population and key in _POPULATION_KEYS:
                # An explicit new interval or window replaces the previous population
                # instead of combining with it, which would match nothing or the wrong
                # games (and would apply an old window to the new interval).
                continue
            if not getattr(scope, key) and prior.get(key):
                value = _typed(key, prior[key])
                if key == "game_ids":
                    # Only anchors that exist in this release are inheritable.
                    value = [game_id for game_id in value if game_id in known_games]
                    if not value:
                        continue
                updates[key] = value
        if different_player:
            updates["player_ids"] = []
        scope = scope.model_copy(update=updates)
    if (
        referential
        and not scope.requires_clarification
        and scope.comparison is None
        and not _anchored(scope)
    ):
        scope = scope.model_copy(
            update={
                "requires_clarification": True,
                "clarification_reason": "missing_reference",
                "clarification_question": (
                    "Which archived game does that refer to? I can only use games in this release."
                ),
                "clarification_options": [
                    f"{game.game_date}: {game.away_team_id} at {game.home_team_id}"
                    for game in games[-8:]
                ],
            }
        )
    return scope


def reclassify_with_subject(scope: ResolvedQuery, question: str) -> ResolvedQuery:
    """Decide the operation again once the follow-up's subject is inherited.

    A pronoun follow-up names no player, so the first pass decides the operation without
    a subject and reads a player ask as the team ask it resembles ("how many games did he
    score at least 25?" becomes a team score threshold). A singular anaphor is what makes
    the inherited player the subject: "their average scoring" stays the team's, because
    the plural may be the team. The inherited player is verified state, so the decision is
    taken again with it and only its measure fields are adopted: the resolved metric, stat,
    threshold and aggregation stay authoritative. A decision that still needs a
    clarification or a refusal is not adopted, and a comparison keeps the measure its own
    groups were resolved from.
    """
    if scope.comparison is not None or not _ANAPHOR.search(question):
        return scope
    decision = classify_operation(
        question,
        has_player=True,
        ambiguous_player=False,
        periods=tuple(scope.periods),
        metric=scope.metric,
        performance_scope=(
            "game"
            if len(scope.game_ids) == 1
            else "population"
            if scope.game_ids
            or scope.relative_game_count
            or re.search(r"\b(?:season|archive)\b", question, re.I)
            else "unspecified"
        ),
    )
    if decision.operation is None or decision.reason is not None or decision.clarification:
        return scope
    updates: dict[str, Any] = {
        "operation": decision.operation,
        "operation_reason": None,
        "stat": decision.stat or scope.stat,
        "aggregation": decision.aggregation or scope.aggregation,
        "threshold": decision.threshold or scope.threshold,
        "requested_measures": decision.measures or scope.requested_measures,
    }
    if scope.clarification_reason == "ambiguous_metric":
        # The clarification asked for the measurement the inherited subject made answerable.
        updates.update(
            requires_clarification=False,
            clarification_reason=None,
            clarification_question=None,
            clarification_options=[],
        )
    return scope.model_copy(update=updates)
