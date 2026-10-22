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
from app.services.query_dates import date_window
from app.services.query_names import (
    resolve_player_mentions as _resolve_player_mentions,
)
from app.services.query_names import (
    unique_given_names,
)
from app.services.query_policy import SeasonType, is_outcome_subset, resolve_phase
from app.services.query_text import normalize as _normalize
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_METRICS = {
    "point": "points",
    "points": "points",
    "scoring": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "steal": "steals",
    "steals": "steals",
    "block": "blocks",
    "blocks": "blocks",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "plus minus": "plus_minus",
    "three": "three_pointers_made",
    "threes": "three_pointers_made",
}


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


def is_record_request(question: str) -> bool:
    """A record spans both outcomes; explicit subsets still take precedence."""
    q = _normalize(question.replace("–", "-").replace("—", "-"))
    if re.search(r"\b(?:only|in)\s+(?:wins?|loss(?:es)?)\b", q):
        return False
    return bool(
        re.search(r"\brecord\b", q)
        or (re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q))
    )


def _periods(question: str) -> list[int]:
    q = _normalize(question)
    values = {int(value) for value in re.findall(r"\bq([1-9])\b", q)}
    values.update(int(value) for value in re.findall(r"\b([1-9])(?:st|nd|rd|th) quarter\b", q))
    for period, ordinal in enumerate(("first", "second", "third", "fourth"), start=1):
        if re.search(rf"\b{ordinal} quarter\b", q):
            values.add(period)
    if "first half" in q:
        values.update({1, 2})
    if "second half" in q:
        values.update({3, 4})
    if "late fourth" in q or "late 4th" in q:
        values.add(4)
    return sorted(values)


def _metric(question: str) -> str | None:
    q = _normalize(question)
    return next(
        (
            metric
            for phrase, metric in sorted(_METRICS.items(), key=lambda item: -len(item[0]))
            if re.search(rf"\b{re.escape(phrase)}\b", q)
        ),
        None,
    )


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
) -> ResolvedQuery:
    """Resolve canonical entities and filters without model inference."""
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

    q = _normalize(question)
    team_ids = sorted(team_ids_in_text(question) - {"NYK"})
    opponent_id = team_ids[0] if len(team_ids) == 1 else None
    latest_date = games[-1].game_date if games else None
    window = date_window(question, games, latest_date)
    date_start, date_end = window.start, window.end
    explicit_dates = window.dates
    relative_count = window.relative_count
    season_level = not (opponent_id or explicit_dates or relative_count or date_start or date_end)
    phase = resolve_phase(question, season_level=season_level, default=default_season_type)
    named_phase, season_type = phase.named, phase.season_type
    home_away = (
        "home"
        if re.search(r"\bhome\b", q)
        else "away"
        if re.search(r"\b(?:road|away)\b", q)
        else None
    )
    game_result = None
    if not is_record_request(question) and is_outcome_subset(question):
        game_result = (
            "W"
            if re.search(r"\bwins?\b|\bwon\b|\bwinning\b", q)
            else "L"
            if re.search(r"\bloss(?:es)?\b|\blost\b|\blosing\b", q)
            else None
        )

    candidates = games
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
    if relative_count:
        resolved_game_ids = [game.id for game in candidates[-relative_count:]]
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
        player_ids=player_ids,
        team_ids=team_ids,
        opponent_id=opponent_id,
        game_ids=resolved_game_ids,
        date_start=date_start,
        date_end=date_end,
        relative_game_count=relative_count,
        periods=_periods(question),
        season_type=season_type,
        all_phases=phase.all_phases,
        home_away=home_away,
        game_result=game_result,
        metric=_metric(question),
        requires_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
        clarification_options=clarification_options,
        data_version=resolved_version,
    )
