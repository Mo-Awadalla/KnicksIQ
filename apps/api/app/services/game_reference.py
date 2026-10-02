"""Resolve conversation game targets from the last ten messages, never their facts."""

from __future__ import annotations

import re

from app.models.game import Game
from app.services.conversation_memory import HISTORY_MESSAGES
from app.services.query_resolution import ResolvedQuery
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import scope_games, scores

_REFERENCE = re.compile(
    r"\b(?:that (?:\w+ ){0,2}(?:game|stretch|run|possession|quarter|night)|"
    r"this game|same game|then|next|during it|after that|the other game|final possession)\b",
    re.I,
)
_DATES = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def resolve_game_reference(
    question: str,
    current: ResolvedQuery,
    messages: list[dict[str, str]],
    games: list[Game],
) -> ResolvedQuery:
    """Context identifies scope; all statistics still come from release-pinned rows.

    Inspect the newest identifying message first. An ambiguous or unavailable
    newer target must not fall through to an older game. Stale committed facts
    cannot substitute for an anchor outside the transcript's ten-message window.
    """
    if not _REFERENCE.search(question):
        return current
    if _DATES.search(question):
        return current  # The current question can supply its own explicit target.
    for message in reversed(messages[-HISTORY_MESSAGES:]):
        content = message["content"]
        dates = set(_DATES.findall(content))
        q = content.lower()
        if dates:
            # Extract identity only: an assistant's asserted performance is not a filter/fact.
            opponents = team_ids_in_text(content) - {"NYK"}
            selected = [
                g
                for g in games
                if str(g.game_date) in dates
                and (not opponents or opponents & {g.home_team_id, g.away_team_id})
            ]
            if len(dates) != 1:
                return missing_game(current)
        elif message["role"] == "user" and re.search(r"\b(?:game|biggest win|best win)\b", q):
            if _REFERENCE.search(content):
                continue  # An earlier follow-up still needs the same concrete antecedent.
            if not team_ids_in_text(content) - {"NYK"} and not re.search(
                r"\b(?:closest|biggest win|best win|best defensive|most recent|"
                r"january|february|march|april|may|june|july|august|september|"
                r"october|november|december)\b",
                q,
            ):
                continue
            selected = scope_games(content, games)
            if "closest" in q and selected:
                value = min(abs(scores(g)[0] - scores(g)[1]) for g in selected)
                selected = [g for g in selected if abs(scores(g)[0] - scores(g)[1]) == value]
            elif any(term in q for term in ("biggest win", "best win")) and selected:
                value = max(scores(g)[0] - scores(g)[1] for g in selected)
                selected = [g for g in selected if scores(g)[0] - scores(g)[1] == value]
            elif "best defensive game" in q and selected:
                value = min(scores(g)[1] for g in selected)
                selected = [g for g in selected if scores(g)[1] == value]
            elif "most recent" in q and selected:
                selected = selected[-1:]
            if re.search(r"\bloss\b", q):
                selected = [g for g in selected if scores(g)[0] < scores(g)[1]]
            elif re.search(r"\bwin\b", q):
                selected = [g for g in selected if scores(g)[0] > scores(g)[1]]
        else:
            continue
        if len(selected) != 1:
            return missing_game(current)
        game = selected[0]
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        if (current.opponent_id and current.opponent_id != opponent) or (
            current.season_type and current.season_type != game.season_type
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
