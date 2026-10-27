"""The typed scope a follow-up turn inherits, and deictic game reference resolution."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Literal

from app.services.query_dates import date_window
from app.services.query_policy import names_phase
from app.services.query_text import (
    is_explanation,
    is_record_request,
    metrics_in_text,
    normalize,
    periods_in_text,
)
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.query_resolution import ResolvedQuery

# A pronoun or a leading connective marks a turn that moves the prior topic, not a new one.
_FOLLOW_UP_MARKER = re.compile(
    r"\b(?:he|him|his|that|another|different player)\b|^\s*(?:why|now|and|what about)\b",
    re.I,
)
# The season as a population; a date window or a named phase is handled elsewhere.
_SEASON_SCOPE = re.compile(
    r"\b(?:this|the|whole|entire|all|rest of the|for the|of the|over the)\s+"
    r"(?:20\d{2}[-–]\d{2}\s+)?season\b|\bseason[- ]long\b",
    re.I,
)
_SITE = re.compile(r"\b(?:home|road|away)\b", re.I)
# A stat or a period is what an elliptical turn asks about; without one it is not a
# continuation of the prior population (an injury question stays a new, unanswerable turn).
_PERIOD = re.compile(
    r"\b(?:quarters?|q[1-4]|[1-4]q|halves|half|halftime|periods?|overtimes?|ot)\b", re.I
)
_SCORE = re.compile(r"\b(?:score|scored|scoring)\b", re.I)


def names_season_scope(question: str) -> bool:
    """True when the question names the season, not a game, window or phase."""
    return bool(_SEASON_SCOPE.search(normalize(question)))


# Asks for many games: an average, a per-game rate, or the best/worst game or win. Over a
# single game these are meaningless, so they cannot continue a one-game turn.
_NEEDS_GAMES = re.compile(
    r"\b(?:average|averaged|averaging|avg|per game|ppg|rpg|apg)\b"
    r"|\b(?:best|worst|most|fewest|highest|lowest|biggest|largest|closest)\b[^?.]{0,30}"
    r"\b(?:games?|wins?|loss(?:es)?|nights?)\b",
    re.I,
)
_THIS_GAME = re.compile(r"\b(?:that|this|the same) game\b", re.I)


def needs_many_games(question: str) -> bool:
    return bool(_NEEDS_GAMES.search(question)) and not _THIS_GAME.search(question)


def is_elliptical_follow_up(question: str, games: list[Game]) -> bool:
    """True when the question cannot pick its own population without the prior turn.

    A question with its own team or opponent, date window, phase, site or season phrase
    stands on its own. A pronoun or connective continues the topic. Beyond those, only a
    stat, score or period question with no population is elliptical: a bare metric, a
    quarter or a player stat needs the previous game or window to mean anything, while a
    question about health or context is a new turn whatever its scope resolves to.
    """
    if _FOLLOW_UP_MARKER.search(question):
        return True
    if team_ids_in_text(question):
        return False
    latest = games[-1].game_date if games else None
    if date_window(question, games, latest).explicit:
        return False
    if names_phase(question) or _SITE.search(question) or names_season_scope(question):
        return False
    return bool(
        metrics_in_text(question)
        or periods_in_text(question)
        or _PERIOD.search(question)
        or _SCORE.search(question)
    )


class InheritedScope(BaseModel):
    """Everything a follow-up turn keeps from the previous accepted turn.

    One structure and one rule: a field the new question names replaces the inherited
    value; every other field is inherited. ``topic`` supplies the subject and metric when
    the follow-up only changes its population. Aggregation travels with the resolved
    scope, so a later turn does not infer it again from the topic wording.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str = ""
    player_ids: list[int] = Field(default_factory=list)
    metric: str | None = None
    aggregation: Literal["average", "total"] | None = None
    requested_metrics: list[str] = Field(default_factory=list)
    requested_aggregations: list[Literal["average", "total"]] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    all_phases: bool = False
    home_away: Literal["home", "away"] | None = None
    opponent_id: str | None = None
    game_result: Literal["W", "L"] | None = None
    date_start: date | None = None
    date_end: date | None = None
    relative_game_count: int | None = None
    relative_from_start: bool = False
    relative_game_order: Literal["first", "last"] = "last"
    game_ids: list[int] = Field(default_factory=list)
    periods: list[int] = Field(default_factory=list)

    def continues_topic(self, question: str, scope: ResolvedQuery) -> bool:
        """True when the follow-up only moves scope, not the subject, metric or answer kind.

        Called after resolution, so the comparison is against the inherited subject and
        the metric the follow-up actually resolved (named metric words included).
        """
        if is_record_request(question) or is_explanation(question):
            return False
        if metrics_in_text(question):
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
