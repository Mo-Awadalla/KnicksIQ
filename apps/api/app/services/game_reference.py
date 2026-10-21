"""Resolve conversation game targets from the last ten messages, never their facts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.models.game import Game
from app.services.conversation_memory import HISTORY_MESSAGES
from app.services.evidence_contracts import VerifiedClaim
from app.services.query_resolution import ResolvedQuery
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import scope_games, scores
from basketball_core.analytics import parse_stat_threshold

_REFERENCE = re.compile(
    r"\b(?:that (?:\w+ ){0,2}(?:game|stretch|run|possession|quarter|night)|"
    r"this game|same game|those games|these games|then|next|during it|after that|"
    r"the other(?: \w+){0,3} game|final possession)\b",
    re.I,
)
_CLAIM_REFERENCE = re.compile(r"\b(?:receipts?|sources?|evidence)\s+for\s+(?:that|this|it)\b", re.I)
_DATES = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


_ACKNOWLEDGEMENT = re.compile(
    r"^\s*(?:thanks|thank you|okay|ok|got it|cool|great|sure)[.!]*\s*$", re.I
)
_PLURAL_REFERENCE = re.compile(
    r"\b(?:(?:all|each)\s+(?:of\s+)?|the\s+other\s+)?(?:those|these)\s+games\b",
    re.I,
)


def _last_user_message(messages: list[dict[str, str]]) -> dict[str, str] | None:
    return next(
        (
            message
            for message in reversed(messages[-HISTORY_MESSAGES:])
            if message["role"] == "user" and not _ACKNOWLEDGEMENT.fullmatch(message["content"])
        ),
        None,
    )


def _has_game_anchor(content: str) -> bool:
    q = content.lower()
    month = (
        r"\b(?:january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\b"
    )
    selector = (
        r"\b(?:biggest win|best win|closest|most recent|first game|last game|"
        r"(?:first|last|final)\s+\d+\s+games?|playoffs?|postseason|"
        r"regular season|home|road|away)\b"
    )
    opponents = team_ids_in_text(content) - {"NYK"}
    return bool(
        _DATES.search(content) or re.search(month, q) or re.search(selector, q) or opponents
    ) and not re.search(r"\bper\s+game\b", q)


def _topic_changed(messages: list[dict[str, str]]) -> bool:
    latest_user = _last_user_message(messages)
    return bool(
        latest_user
        and not _REFERENCE.search(latest_user["content"])
        and not _CLAIM_REFERENCE.search(latest_user["content"])
        and not _has_game_anchor(latest_user["content"])
    )


def _resolve_delivered_game_group(
    current: ResolvedQuery,
    messages: list[dict[str, str]],
    games: list[Game],
    delivered_claims: Sequence[VerifiedClaim],
    prior_intent: str | None,
    prior_scope: dict[str, Any] | None,
) -> ResolvedQuery:
    anchor = _last_user_message(messages)
    if (
        anchor is None
        or prior_intent is None
        or anchor["content"].strip() != prior_intent
        or prior_scope is None
        or prior_scope.get("data_version") != current.data_version
    ):
        return missing_game(current)
    threshold = parse_stat_threshold(prior_intent)
    player_ids = prior_scope.get("player_ids")
    if (
        threshold is None
        or not isinstance(player_ids, list)
        or len(player_ids) != 1
        or type(player_ids[0]) is not int
        or (current.player_ids and current.player_ids != player_ids)
        or current.requires_clarification
        or current.relative_game_count
    ):
        return missing_game(current)

    game_map = {game.id: game for game in games}
    subject = f"player:{player_ids[0]}"
    predicate = {
        "metric_id": threshold.stat,
        "operator": threshold.symbol,
        "cutoff": threshold.value,
    }
    matching_sets = []
    for claim in delivered_claims:
        matching = claim.eligibility.get("matching_game_ids")
        if (
            claim.release_id == current.data_version
            and claim.subject_id == subject
            and claim.metric_id == "games:count"
            and claim.eligibility.get("stat_predicate") == predicate
            and isinstance(matching, list)
            and matching
            and all(type(game_id) is int for game_id in matching)
            and claim.game_ids == matching
            and len(matching) == len(set(matching))
            and set(matching) <= game_map.keys()
        ):
            matching_sets.append(matching)
    if len(matching_sets) != 1:
        return missing_game(current)

    selected = [game_map[game_id] for game_id in matching_sets[0]]
    if (
        bool(set(current.team_ids) - {"NYK"})
        or (
            current.opponent_id
            and any(current.opponent_id not in {g.home_team_id, g.away_team_id} for g in selected)
        )
        or (current.season_type and any(g.season_type != current.season_type for g in selected))
        or (current.home_away == "home" and any(game.home_team_id != "NYK" for game in selected))
        or (current.home_away == "away" and any(game.away_team_id != "NYK" for game in selected))
    ):
        return missing_game(current)

    return current.model_copy(
        update={
            "game_ids": list(matching_sets[0]),
            "date_start": None,
            "date_end": None,
            "relative_game_count": None,
            "requires_clarification": False,
            "clarification_reason": None,
            "clarification_options": [],
        }
    )


def resolve_game_reference(
    question: str,
    current: ResolvedQuery,
    messages: list[dict[str, str]],
    games: list[Game],
    *,
    delivered_claims: Sequence[VerifiedClaim] = (),
    prior_intent: str | None = None,
    prior_scope: dict[str, Any] | None = None,
) -> ResolvedQuery:
    """Use recent messages or delivered claim identities as scope, never as facts."""
    # Generic receipts may cover verified multi-game claims, not one selected game.
    if not _REFERENCE.search(question) and (
        not _CLAIM_REFERENCE.search(question) or delivered_claims
    ):
        return current
    recent = messages[-HISTORY_MESSAGES:]
    if _PLURAL_REFERENCE.search(question):
        if current.date_start or current.date_end:
            return missing_game(current)
        return _resolve_delivered_game_group(
            current,
            recent,
            games,
            delivered_claims,
            prior_intent,
            prior_scope,
        )
    if current.date_start or current.date_end:
        return current
    if current.relative_game_count is not None:
        return current if current.game_ids else missing_game(current)
    if prior_scope is not None and prior_scope.get("data_version") != current.data_version:
        return missing_game(current)
    if _topic_changed(recent):
        return missing_game(current)

    for message in reversed(recent):
        content = message["content"]
        dates = set(_DATES.findall(content))
        q = content.lower()
        if dates:
            opponents = team_ids_in_text(content) - {"NYK"}
            selected = [
                game
                for game in games
                if str(game.game_date) in dates
                and (not opponents or opponents & {game.home_team_id, game.away_team_id})
            ]
            if len(dates) != 1:
                return missing_game(current)
        elif message["role"] == "user" and _has_game_anchor(content):
            if _REFERENCE.search(content):
                continue
            if not team_ids_in_text(content) - {"NYK"} and not re.search(
                r"\b(?:closest|biggest win|best win|best defensive|most recent|"
                r"first game|last game|(?:first|last|final)\s+\d+\s+games?|"
                r"playoffs?|postseason|regular season|home|road|away|"
                r"january|february|march|april|may|june|july|august|september|"
                r"october|november|december)\b",
                q,
            ):
                continue
            selected = scope_games(content, games)
            if "closest" in q and selected:
                value = min(abs(scores(game)[0] - scores(game)[1]) for game in selected)
                selected = [
                    game for game in selected if abs(scores(game)[0] - scores(game)[1]) == value
                ]
            elif any(term in q for term in ("biggest win", "best win")) and selected:
                value = max(scores(game)[0] - scores(game)[1] for game in selected)
                selected = [game for game in selected if scores(game)[0] - scores(game)[1] == value]
            elif "best defensive game" in q and selected:
                value = min(scores(game)[1] for game in selected)
                selected = [game for game in selected if scores(game)[1] == value]
            elif "most recent" in q and selected:
                selected = selected[-1:]
            if re.search(r"\bloss\b", q):
                selected = [game for game in selected if scores(game)[0] < scores(game)[1]]
            elif re.search(r"\bwin\b", q):
                selected = [game for game in selected if scores(game)[0] > scores(game)[1]]
        else:
            continue
        if len(selected) != 1:
            return missing_game(current)
        game = selected[0]
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        if (
            (current.opponent_id and current.opponent_id != opponent)
            or (current.season_type and current.season_type != game.season_type)
            or (current.home_away == "home" and game.home_team_id != "NYK")
            or (current.home_away == "away" and game.away_team_id != "NYK")
        ):
            return missing_game(current)
        return current.model_copy(
            update={
                "game_ids": [game.id],
                "date_start": game.game_date,
                "date_end": game.game_date,
                "opponent_id": opponent,
                "team_ids": [opponent],
                "season_type": game.season_type,
            }
        )
    return missing_game(current)


def missing_game(scope: ResolvedQuery) -> ResolvedQuery:
    return scope.model_copy(
        update={
            "game_ids": [],
            "date_start": None,
            "date_end": None,
            "requires_clarification": True,
            "clarification_reason": "missing_conversation_game",
            "clarification_options": ["Which game?"],
        }
    )
