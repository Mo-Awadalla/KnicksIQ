"""Basketball-specific deterministic query resolution for the active release."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.query_dates import MONTH_WORDS, date_window
from app.services.query_game_scope import InheritedScope, referenced_game
from app.services.query_names import (
    resolve_player_mentions as _resolve_player_mentions,
)
from app.services.query_names import (
    unique_given_names,
)
from app.services.query_policy import (
    Phase,
    SeasonType,
    is_outcome_subset,
    names_phase,
    resolve_phase,
)
from app.services.query_text import (
    METRIC_WORDS,
    is_explanation,
    is_record_request,
    metric_in_text,
    normalize,
    periods_in_text,
)
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ResolvedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    player_ids: list[int] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    opponent_id: str | None = None
    game_ids: list[int] = Field(default_factory=list)
    date_start: date | None = None
    date_end: date | None = None
    relative_game_count: int | None = None
    # "First 10 games" counts from the start of the scope; "last 10" from the end.
    relative_from_start: bool = False
    periods: list[int] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    # The user asked for every phase; distinguishes None from "unspecified" for merges.
    all_phases: bool = False
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    metric: str | None = None
    requires_clarification: bool = False
    clarification_reason: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    data_version: str

    def window[T](self, ordered: list[T]) -> list[T]:
        """Apply the relative game window to a chronologically ordered list."""
        count = self.relative_game_count
        if not count:
            return ordered
        return ordered[:count] if self.relative_from_start else ordered[-count:]

    def retrieval_filters(self) -> dict[str, object]:
        filters: dict[str, object] = {
            "player_ids": self.player_ids,
            "team_ids": self.team_ids,
            "game_ids": self.game_ids,
            "periods": self.periods,
            "season_types": [self.season_type] if self.season_type else [],
            "dates": [],
        }
        if self.date_start and self.date_end and self.date_start == self.date_end:
            filters["dates"] = [self.date_start.isoformat()]
        return filters

    def planner_filters(self) -> dict[str, list[object]]:
        """Return the exact filter schema shared by lexical and dense retrieval."""
        return {
            "dates": (
                [self.date_start.isoformat()]
                if self.date_start and self.date_end and self.date_start == self.date_end
                else []
            ),
            "team_ids": list(self.team_ids),
            "player_ids": list(self.player_ids),
            "game_ids": list(self.game_ids),
            "periods": list(self.periods),
            "season_types": [self.season_type] if self.season_type else [],
        }


async def _active_release(
    db: AsyncSession,
    data_version: str | None,
) -> tuple[int | None, str]:
    stmt = select(DatasetRelease.id, DatasetRelease.version).where(
        DatasetRelease.validation_passed.is_(True)
    )
    if data_version:
        stmt = stmt.where(DatasetRelease.version == data_version)
    else:
        stmt = stmt.where(DatasetRelease.status == "active").order_by(
            DatasetRelease.activated_at.desc(),
            DatasetRelease.id.desc(),
        )
    row = (await db.execute(stmt.limit(1))).one_or_none()
    return (row[0], row[1]) if row else (None, data_version or "test-seed")


async def resolve_query(
    db: AsyncSession,
    question: str,
    *,
    intent: str,
    data_version: str | None = None,
    typo_threshold: float = 0.86,
    default_season_type: SeasonType | None = "regular",
    default_all_phases: bool = False,
    inherit: InheritedScope | None = None,
) -> ResolvedQuery:
    """Resolve canonical entities and filters without model inference.

    ``inherit`` supplies the previous accepted turn's scope and topic as the default
    values for everything this question does not name, before candidate selection, so
    the resolved game ids and phase stay consistent with each other.
    """
    release_id, resolved_version = await _active_release(db, data_version)
    game_stmt = select(Game).where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
    if release_id is not None:
        game_stmt = game_stmt.where(Game.release_id == release_id)
    games = list((await db.execute(game_stmt.order_by(Game.game_date, Game.id))).scalars().all())
    game_ids = [game.id for game in games]

    player_stmt = select(Player).order_by(Player.full_name)
    if release_id is not None:
        player_stmt = (
            player_stmt.join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
            .where(PlayerGameStat.release_id == release_id)
            .distinct()
        )
    players = list((await db.execute(player_stmt)).scalars().all())
    player_ids, ambiguous_players = _resolve_player_mentions(
        question,
        players,
        typo_threshold=typo_threshold,
        unique_givens=unique_given_names(players),
    )

    q = normalize(question)
    team_ids = sorted(team_ids_in_text(question) - {"NYK"})
    if team_ids:
        opponent_id = team_ids[0] if len(team_ids) == 1 else None
    else:
        opponent_id = inherit.opponent_id if inherit else None
    latest_date = games[-1].game_date if games else None
    window = date_window(question, games, latest_date)
    date_start, date_end = window.start, window.end
    explicit_dates = window.dates
    relative_count = window.relative_count
    relative_from_start = window.relative_from_start

    named_phase = names_phase(question)
    named_site = (
        "home"
        if re.search(r"\bhome\b", q)
        else "away"
        if re.search(r"\b(?:road|away)\b", q)
        else None
    )
    reference = referenced_game(question, inherit, games)
    named_window = bool(window.explicit or reference)
    # Game ids are the prior window's output, not an input: they may bound an elliptical
    # turn only when it names no opponent, site or outcome of its own.
    inherited_games: list[int] = []
    if reference:
        # A deictic game reference names the whole window, not only one filter.
        date_start = date_end = reference.game_date
        relative_count = None
    elif inherit is not None and not named_window and not named_phase:
        relative_count = inherit.relative_game_count
        relative_from_start = inherit.relative_from_start
        date_start = inherit.date_start
        date_end = inherit.date_end
        if not team_ids and named_site is None and not is_outcome_subset(question):
            inherited_games = inherit.game_ids
    season_level = not (opponent_id or explicit_dates or relative_count or date_start or date_end)
    if inherit is not None and not named_phase:
        phase = Phase(named=False, season_type=inherit.season_type, all_phases=inherit.all_phases)
    else:
        phase = resolve_phase(
            question,
            season_level=season_level,
            default=default_season_type,
            default_all_phases=default_all_phases,
        )
    named_phase, season_type = phase.named, phase.season_type
    home_away = named_site or (inherit.home_away if inherit else None)
    if is_record_request(question):
        game_result = None
    elif is_outcome_subset(question):
        game_result = (
            "W"
            if re.search(r"\bwins?\b|\bwon\b|\bwinning\b", q)
            else "L"
            if re.search(r"\bloss(?:es)?\b|\blost\b|\blosing\b", q)
            else None
        )
    else:
        game_result = inherit.game_result if inherit else None

    if player_ids or ambiguous_players:
        resolved_player_ids = player_ids
    elif inherit is not None:
        resolved_player_ids = inherit.player_ids
    else:
        resolved_player_ids = []
    periods = periods_in_text(question)
    if not periods and inherit is not None:
        periods = inherit.periods
    metric = metric_in_text(question)
    if is_record_request(question) or is_explanation(question):
        metric = None
    elif metric is None and inherit is not None:
        metric = inherit.metric

    candidates = [reference] if reference else games
    if inherited_games:
        inherited_ids = set(inherited_games)
        candidates = [game for game in candidates if game.id in inherited_ids]
    if opponent_id:
        candidates = [
            game for game in candidates if opponent_id in {game.home_team_id, game.away_team_id}
        ]
    if explicit_dates and not re.search(r"\b(between|from|through|until)\b", q):
        candidates = [game for game in candidates if game.game_date in explicit_dates]
    if season_type:
        candidates = [game for game in candidates if game.season_type == season_type]
    if home_away == "home":
        candidates = [game for game in candidates if game.home_team_id == "NYK"]
    elif home_away == "away":
        candidates = [game for game in candidates if game.away_team_id == "NYK"]
    if date_start:
        candidates = [game for game in candidates if game.game_date >= date_start]
    if date_end:
        candidates = [game for game in candidates if game.game_date <= date_end]
    if game_result:
        candidates = [
            game
            for game in candidates
            if (
                (game.home_score if game.home_team_id == "NYK" else game.away_score)
                > (game.away_score if game.home_team_id == "NYK" else game.home_score)
            )
            == (game_result == "W")
        ]

    descriptive_reference = bool(
        (bool(explicit_dates) and not re.search(r"\b(between|from|through|until)\b", q))
        or re.search(r"\bovertime game\b", q)
        or re.search(r"\bgame where\b", q)
        or (
            opponent_id
            # per/each/a game count a population, not one game.
            and not re.search(r"\b(?:per|each|a)\s+game\b", q)
            and re.search(r"\b(?:the|that|most recent)?\s*game\b", q)
            and "games" not in q
        )
    )
    if ("biggest win" in q or "best win" in q) and candidates:
        candidates = [
            max(
                candidates,
                key=lambda game: (
                    (game.home_score if game.home_team_id == "NYK" else game.away_score)
                    - (game.away_score if game.home_team_id == "NYK" else game.home_score),
                    game.game_date,
                    game.id,
                ),
            )
        ]
        descriptive_reference = True
    if "best defensive game" in q and candidates:
        candidates = [
            min(
                candidates,
                key=lambda game: (
                    game.away_score if game.home_team_id == "NYK" else game.home_score,
                    game.game_date,
                    game.id,
                ),
            )
        ]
        descriptive_reference = True
    if "overtime game" in q and game_ids:
        overtime_ids = set(
            (
                await db.execute(
                    select(GameEvent.game_id)
                    .where(GameEvent.game_id.in_(game_ids), GameEvent.period > 4)
                    .distinct()
                )
            ).scalars()
        )
        candidates = [game for game in candidates if game.id in overtime_ids]
    scored_match = re.search(r"\bscored\s+(\d+)\b", q)
    if scored_match and game_ids:
        stat_stmt = select(PlayerGameStat.game_id).where(
            PlayerGameStat.game_id.in_(game_ids),
            PlayerGameStat.points == int(scored_match.group(1)),
        )
        if player_ids:
            stat_stmt = stat_stmt.where(PlayerGameStat.player_id.in_(player_ids))
        matching_stat_games = set((await db.execute(stat_stmt)).scalars())
        candidates = [game for game in candidates if game.id in matching_stat_games]
        descriptive_reference = True

    resolved_game_ids: list[int] = []
    if reference:
        resolved_game_ids = [reference.id]
    elif relative_count:
        selected = (
            candidates[:relative_count] if relative_from_start else candidates[-relative_count:]
        )
        resolved_game_ids = [game.id for game in selected]
    elif inherited_games:
        resolved_game_ids = [game.id for game in candidates]
    elif descriptive_reference:
        if "most recent" in q and candidates:
            resolved_game_ids = [candidates[-1].id]
        elif len(candidates) == 1:
            resolved_game_ids = [candidates[0].id]
    elif any((opponent_id, date_start, date_end, home_away, game_result)) or named_phase:
        resolved_game_ids = [game.id for game in candidates]

    clarification_options = ambiguous_players
    clarification_reason = "ambiguous_player" if ambiguous_players else None
    if descriptive_reference and len(candidates) > 1 and not resolved_game_ids:
        clarification_reason = "ambiguous_game"
        clarification_options = [
            f"{game.game_date}: {game.away_team_id} at {game.home_team_id}"
            for game in candidates[:8]
        ]

    return ResolvedQuery(
        intent=intent,
        player_ids=resolved_player_ids,
        team_ids=team_ids,
        opponent_id=opponent_id,
        game_ids=resolved_game_ids,
        date_start=date_start,
        date_end=date_end,
        relative_game_count=relative_count,
        relative_from_start=bool(relative_count) and relative_from_start,
        periods=periods,
        season_type=season_type,
        all_phases=phase.all_phases,
        home_away=home_away,
        game_result=game_result,
        metric=metric,
        requires_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
        clarification_options=clarification_options,
        data_version=resolved_version,
    )


# Words a scope-only phrase may contain besides metric words, months and numbers.
_SCOPE_WORDS = frozenset(
    "a an and at the their them they his her its s on in of for during vs versus against "
    "home road away playoff playoffs postseason regular season overall all phases phase "
    "including play first last opening final next previous recent games game stretch "
    "wins win losses loss won lost record per average total quarter quarters half halves "
    "overtime ot 1st 2nd 3rd 4th third fourth before after since between from through "
    "to until star break christmas month week weeks".split()
)


async def phrase_names_scope(db: AsyncSession, phrase: str, data_version: str | None) -> bool:
    """True when "what about <phrase>" names a known subject or only moves scope.

    A phrase that names a resolved player or opponent is a known subject. Otherwise every
    word must be scope vocabulary, so "Nobody McFake's points" still counts as an
    unknown subject even though "points" is a recognised metric.
    """
    named = await resolve_query(db, phrase, intent="analyst", data_version=data_version)
    if named.player_ids or named.opponent_id:
        return True
    leftover = {
        word
        for word in normalize(phrase).split()
        if not word.isdigit()
        and word not in _SCOPE_WORDS
        and word not in METRIC_WORDS
        and word not in MONTH_WORDS
    }
    return not leftover
