"""The typed scope a follow-up turn inherits, and deictic game reference resolution."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Literal

from app.services.query_text import is_explanation, is_record_request, metric_in_text, normalize
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.query_resolution import ResolvedQuery


class InheritedScope(BaseModel):
    """Everything a follow-up turn keeps from the previous accepted turn.

    One structure and one rule: a field the new question names replaces the inherited
    value; every other field is inherited. ``topic`` is the question that gives the turn
    its subject and metric when the follow-up itself only moves phase, window, site,
    opponent or game reference. ``aggregation`` is not part of a resolved scope, so it
    travels with the topic question instead of being re-derived per key.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = ""
    player_ids: list[int] = Field(default_factory=list)
    metric: str | None = None
    aggregation: Literal["average", "total"] | None = None
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    all_phases: bool = False
    home_away: Literal["home", "away"] | None = None
    opponent_id: str | None = None
    game_result: Literal["W", "L"] | None = None
    date_start: date | None = None
    date_end: date | None = None
    relative_game_count: int | None = None
    relative_from_start: bool = False
    game_ids: list[int] = Field(default_factory=list)
    periods: list[int] = Field(default_factory=list)

    def continues_topic(self, question: str, scope: ResolvedQuery) -> bool:
        """True when the follow-up only moves scope, not the subject, metric or answer kind.

        Called after resolution, so the comparison is against the inherited subject and
        the metric the follow-up actually resolved (named metric words included).
        """
        if is_record_request(question) or is_explanation(question):
            return False
        if metric_in_text(question) is not None:
            return False
        return set(scope.player_ids) == set(self.player_ids)


def referenced_game(
    question: str, inherited: InheritedScope | None, games: list[Game]
) -> Game | None:
    """The archived game a deictic follow-up keeps under discussion, if any."""
    if inherited is None or re.search(r"\b20\d{2}-\d{2}-\d{2}\b", question):
        return None
    q = normalize(question)
    previous = bool(re.search(r"\bgame\s+before\s+that\b", q))
    if not previous and not re.search(r"\b(?:that|this|the)\s+game\b", q):
        return None
    by_id = {game.id: game for game in games}
    referenced = [by_id[game_id] for game_id in inherited.game_ids if game_id in by_id]
    if not referenced and inherited.date_start:
        end = inherited.date_end or inherited.date_start
        referenced = [game for game in games if inherited.date_start <= game.game_date <= end]
    if not referenced:
        return None
    if previous:
        earlier = [
            game
            for game in games
            if (game.game_date, game.id) < (referenced[0].game_date, referenced[0].id)
        ]
        return earlier[-1] if earlier else None
    return referenced[-1]
