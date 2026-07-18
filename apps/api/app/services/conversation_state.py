"""Structured conversation state and deterministic follow-up deltas."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from app.services.query_resolution import ResolvedQuery
from pydantic import BaseModel, ConfigDict, Field


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_ids: list[int] = Field(default_factory=list)
    game_ids: list[int] = Field(default_factory=list)
    opponent_id: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    periods: list[int] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    metric: str | None = None
    route: str | None = None
    data_version: str | None = None


_FOLLOW_UP_RE = re.compile(
    r"^\s*(?:and\b|what about\b|how about\b|why\b|then\b|in that\b|"
    r"what happened next\b|who\b.+\bthen\b|how long\b|did they\b|"
    r"show me\b|was that\b|compare that\b|tell me more\b|"
    r"that game\b|those games\b|he\b|his\b|they\b|their\b)",
    re.IGNORECASE,
)
_PRONOUN_RE = re.compile(
    r"\b(?:he|him|his|she|her|they|them|their|that|those|then)\b",
    re.I,
)


def resolve_conversation_delta(
    question: str,
    current: ResolvedQuery,
    prior: ConversationState | None,
) -> tuple[ResolvedQuery, ConversationState]:
    """Apply a follow-up delta while clearing state on explicit topic changes."""
    if prior is None:
        return current, state_from_resolved(current)

    follow_up = bool(_FOLLOW_UP_RE.search(question))
    explicit_subject_change = bool(
        (current.player_ids and current.player_ids != prior.player_ids)
        or (current.opponent_id and prior.opponent_id and current.opponent_id != prior.opponent_id)
        or (current.game_ids and prior.game_ids and current.game_ids != prior.game_ids)
    )
    inherit = follow_up and not explicit_subject_change
    if _PRONOUN_RE.search(question):
        ambiguous_options: list[str] = []
        if len(prior.player_ids) > 1:
            ambiguous_options.extend(f"player:{value}" for value in prior.player_ids)
        if len(prior.game_ids) > 1 and re.search(r"\b(?:that|it|game)\b", question, re.I):
            ambiguous_options.extend(f"game:{value}" for value in prior.game_ids)
        if ambiguous_options:
            current = current.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_reason": "ambiguous_conversation_reference",
                    "clarification_options": ambiguous_options,
                }
            )

    if inherit:
        current = current.model_copy(
            update={
                "player_ids": current.player_ids or prior.player_ids,
                "game_ids": current.game_ids or prior.game_ids,
                "opponent_id": current.opponent_id or prior.opponent_id,
                "team_ids": current.team_ids or ([prior.opponent_id] if prior.opponent_id else []),
                "date_start": current.date_start or prior.date_start,
                "date_end": current.date_end or prior.date_end,
                "periods": current.periods or prior.periods,
                "season_type": current.season_type or prior.season_type,
                "home_away": current.home_away or prior.home_away,
                "game_result": current.game_result or prior.game_result,
                "metric": current.metric or prior.metric,
            }
        )
    return current, state_from_resolved(current)


def state_from_resolved(resolved: ResolvedQuery) -> ConversationState:
    return ConversationState(
        player_ids=resolved.player_ids,
        game_ids=resolved.game_ids,
        opponent_id=resolved.opponent_id,
        date_start=resolved.date_start,
        date_end=resolved.date_end,
        periods=resolved.periods,
        season_type=resolved.season_type,
        home_away=resolved.home_away,
        game_result=resolved.game_result,
        metric=resolved.metric,
        route=resolved.intent,
        data_version=resolved.data_version,
    )
