"""Basketball-specific deterministic query resolution for the active release."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_CURATED_PLAYER_ALIASES = {
    "jb": "Jalen Brunson",
    "brunson": "Jalen Brunson",
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "og": "OG Anunoby",
}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
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
_NAME_STOPWORDS = {
    "against",
    "average",
    "before",
    "compare",
    "game",
    "games",
    "home",
    "knicks",
    "last",
    "losses",
    "month",
    "points",
    "previous",
    "road",
    "season",
    "since",
    "the",
    "this",
    "wins",
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
        filters = self.retrieval_filters()
        return {
            "dates": list(filters["dates"]),
            "team_ids": list(filters["team_ids"]),
            "player_ids": list(filters["player_ids"]),
            "game_ids": list(filters["game_ids"]),
            "periods": list(filters["periods"]),
            "season_types": list(filters["season_types"]),
        }


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def _player_aliases(player: Player) -> set[str]:
    normalized = _normalize(player.full_name)
    parts = normalized.split()
    aliases = {normalized, parts[-1]}
    if len(parts) > 1:
        aliases.add(f"{parts[0][0]} {parts[-1]}")
    aliases.update(
        alias for alias, target in _CURATED_PLAYER_ALIASES.items() if target == player.full_name
    )
    return aliases


def _name_candidates(question: str) -> list[str]:
    candidates: list[str] = []
    for raw in re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}(?:\s+[A-Za-z][A-Za-z'-]{2,})?\b", question):
        normalized = _normalize(raw)
        words = normalized.split()
        if words and not all(word in _NAME_STOPWORDS for word in words):
            candidates.append(normalized)
            if len(words) == 2:
                candidates.extend(words)
    return list(dict.fromkeys(candidates))


def _resolve_player_mentions(
    question: str,
    players: list[Player],
    *,
    typo_threshold: float,
    allow_fuzzy: bool = True,
) -> tuple[list[int], list[str]]:
    normalized_question = f" {_normalize(question)} "
    aliases: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        for alias in _player_aliases(player):
            aliases[alias].append(player)

    resolved: dict[int, Player] = {}
    ambiguous: dict[int, Player] = {}
    remaining = normalized_question
    # Full names and curated aliases are authoritative and consume their spans
    # before ambiguous surname matching.
    for player in sorted(players, key=lambda item: -len(_normalize(item.full_name))):
        full_name = _normalize(player.full_name)
        if re.search(rf"\b{re.escape(full_name)}\b", remaining):
            resolved[player.id] = player
            remaining = re.sub(rf"\b{re.escape(full_name)}\b", " ", remaining)
    for alias, target in sorted(
        _CURATED_PLAYER_ALIASES.items(),
        key=lambda item: -len(item[0]),
    ):
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = [player for player in players if player.full_name == target]
            resolved.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    for alias in sorted(aliases, key=len, reverse=True):
        if alias in _CURATED_PLAYER_ALIASES:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            curated_target = _CURATED_PLAYER_ALIASES.get(alias)
            matches = (
                [player for player in aliases[alias] if player.full_name == curated_target]
                if curated_target
                else aliases[alias]
            )
            knicks_matches = [player for player in matches if player.team_id == "NYK"]
            if len(matches) > 1 and len(knicks_matches) == 1:
                matches = knicks_matches
            if len(matches) == 1:
                resolved[matches[0].id] = matches[0]
            else:
                ambiguous.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    if allow_fuzzy and not resolved and not ambiguous:
        for candidate in _name_candidates(question):
            scores = [
                (
                    max(
                        SequenceMatcher(None, candidate, alias).ratio()
                        for alias in _player_aliases(player)
                    ),
                    player,
                )
                for player in players
            ]
            scores.sort(key=lambda item: (-item[0], item[1].id))
            if not scores or scores[0][0] < typo_threshold:
                continue
            best_score = scores[0][0]
            close = [player for score, player in scores if best_score - score < 0.06]
            if len(close) == 1:
                resolved[close[0].id] = close[0]
            else:
                ambiguous.update({player.id: player for player in close})
            break
    return sorted(resolved), sorted(player.full_name for player in ambiguous.values())


def _periods(question: str) -> list[int]:
    q = _normalize(question)
    values = {int(value) for value in re.findall(r"\bq([1-9])\b", q)}
    values.update(int(value) for value in re.findall(r"\b([1-9])(?:st|nd|rd|th) quarter\b", q))
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
    postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    player_ids, ambiguous_players = _resolve_player_mentions(
        question,
        players,
        typo_threshold=typo_threshold,
        allow_fuzzy=not postgres,
    )
    if not player_ids and not ambiguous_players and postgres:
        # pg_trgm proposes a deliberately small candidate set; the stricter
        # deterministic similarity/margin checks above still decide whether
        # automatic typo resolution is safe.
        proposed: dict[int, Player] = {}
        for candidate in _name_candidates(question):
            similarity = func.word_similarity(candidate, func.lower(Player.full_name))
            proposal_stmt = (
                select(Player)
                .where(similarity >= 0.3)
                .order_by(similarity.desc(), Player.id)
                .limit(5)
            )
            for player in (await db.execute(proposal_stmt)).scalars():
                proposed[player.id] = player
        if proposed:
            player_ids, ambiguous_players = _resolve_player_mentions(
                question,
                list(proposed.values()),
                typo_threshold=typo_threshold,
            )

    q = _normalize(question)
    team_ids = sorted(team_ids_in_text(question) - {"NYK"})
    opponent_id = team_ids[0] if len(team_ids) == 1 else None
    explicit_dates = [
        date.fromisoformat(value) for value in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", question)
    ]
    date_start = explicit_dates[0] if explicit_dates else None
    date_end = explicit_dates[-1] if explicit_dates else None
    latest_date = games[-1].game_date if games else None
    relative_count: int | None = None
    count_match = re.search(r"\blast\s+(\d+)\s+games?\b", q)
    if count_match:
        relative_count = max(1, min(int(count_match.group(1)), 82))
    elif re.search(r"\b(?:last|previous)\s+game\b", q):
        relative_count = 1

    if latest_date and "this month" in q:
        date_start = latest_date.replace(day=1)
        date_end = latest_date
    else:
        named_month = next((month for name, month in _MONTHS.items() if name in q), None)
        if named_month and games:
            month_dates = [game.game_date for game in games if game.game_date.month == named_month]
            if month_dates:
                date_start, date_end = min(month_dates), max(month_dates)
    if explicit_dates and "since" in q:
        date_end = latest_date
    elif explicit_dates and "before" in q:
        date_start = games[0].game_date if games else None
        date_end = explicit_dates[0]

    season_type = (
        "playoffs"
        if "playoff" in q or "postseason" in q
        else "play_in"
        if "play in" in q
        else "regular"
        if "regular season" in q
        else None
    )
    home_away = (
        "home"
        if re.search(r"\bhome\b", q)
        else "away"
        if re.search(r"\b(?:road|away)\b", q)
        else None
    )
    game_result = (
        "W" if re.search(r"\bwins?\b", q) else "L" if re.search(r"\bloss(?:es)?\b", q) else None
    )

    candidates = games
    if opponent_id:
        candidates = [
            game for game in candidates if opponent_id in {game.home_team_id, game.away_team_id}
        ]
    if explicit_dates:
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
        explicit_dates
        or "overtime game" in q
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
    elif any((opponent_id, date_start, date_end, season_type, home_away, game_result)):
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
        home_away=home_away,
        game_result=game_result,
        metric=_metric(question),
        requires_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
        clarification_options=clarification_options,
        data_version=resolved_version,
    )
