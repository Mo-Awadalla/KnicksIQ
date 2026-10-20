"""Basketball-specific deterministic query resolution for the active release."""

from __future__ import annotations

import calendar
import datetime
import re
from datetime import date, timedelta
from typing import Literal

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.opponent_narrowing import narrow_by_condition, requires_lead_change
from app.services.query_parsing import (
    _MONTHS,
    _explicit_dates,
    _metric,
    _name_candidates,
    _normalize,
    _periods,
    _resolve_player_mentions,
    is_game_score_request,
    is_live_only_score_request,  # noqa: F401
    is_record_request,
)
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import scores
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def all_star_end(season: str) -> date | None:
    """Supported archive calendar boundary, verified at nba.com/allstar/2026."""
    return {"2025-26": date(2026, 2, 15)}.get(season)


class CalendarBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["all_star_end"] = "all_star_end"
    date: datetime.date
    relation: Literal[">", "<="]
    source_url: Literal["https://www.nba.com/allstar/2026"] = "https://www.nba.com/allstar/2026"


class ResolvedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    player_ids: list[int] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    opponent_id: str | None = None
    game_ids: list[int] = Field(default_factory=list)
    date_start: date | None = None
    date_end: date | None = None
    calendar_boundary: CalendarBoundary | None = None
    relative_game_count: int | None = None
    relative_game_order: Literal["first", "last"] = "last"
    periods: list[int] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    metric: str | None = None
    requires_clarification: bool = False
    clarification_reason: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    data_version: str

    def requested_window(
        self, *, relative_unit: Literal["games", "appearances"]
    ) -> dict[str, object]:
        window: dict[str, object] = {}
        if self.date_start:
            window["date_start"] = self.date_start.isoformat()
        if self.date_end:
            window["date_end"] = self.date_end.isoformat()
        if self.relative_game_count:
            window.update(
                relative_game_count=self.relative_game_count,
                relative_game_order=self.relative_game_order,
                relative_unit=relative_unit,
            )
        if self.calendar_boundary:
            window["calendar_boundary"] = self.calendar_boundary.model_dump(mode="json")
        return window

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
    select_extrema: bool = True,
) -> ResolvedQuery:
    """Resolve canonical entities and filters without model inference.

    Narrative computation retains the comparison population with select_extrema=False;
    archive retrieval and conversation references retain the selected targets.
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
    explicit_dates, date_error = _explicit_dates(question, games)
    date_start = explicit_dates[0] if explicit_dates else None
    date_end = explicit_dates[-1] if explicit_dates else None
    latest_date = games[-1].game_date if games else None
    named_months = {month for name, month in _MONTHS.items() if re.search(rf"\b{name}\b", q)}
    comparison = bool(
        re.search(r"\b(?:compare|comparison|versus|vs|better|stronger)\b", q)
        or re.search(r"\b(?:home or away|eastern or western)\b", q)
    )
    month_comparison = comparison and len(named_months) > 1 and not explicit_dates
    relative_count: int | None = None
    count_match = re.search(r"\b(?:last|final|first)\s+(\d+)\s+(?:regular season\s+)?games?\b", q)
    if count_match:
        relative_count = max(1, min(int(count_match.group(1)), 82))
    elif re.search(r"\b(?:last|previous)\s+game\b", q):
        relative_count = 1

    if not explicit_dates and not date_error and latest_date and "this month" in q:
        date_start = latest_date.replace(day=1)
        date_end = latest_date
    elif not explicit_dates and not date_error:
        if named_months and games:
            # A comparison needs every requested month, not the first named one.
            selected_months = named_months if month_comparison else {min(named_months)}
            month_dates = [
                game.game_date for game in games if game.game_date.month in selected_months
            ]
            if month_dates:
                first, last = min(month_dates), max(month_dates)
                date_start = first.replace(day=1)
                date_end = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    if explicit_dates and "since" in q:
        date_end = latest_date
    elif explicit_dates and "before" in q and "all star" not in q:
        date_start = games[0].game_date if games else None
        date_end = explicit_dates[0]
    calendar_error = None
    calendar_boundary = None
    if "all star" in q:
        boundary = all_star_end(games[0].season) if games else None
        if boundary is None:
            calendar_error = "unsupported_all_star_boundary"
        elif not date_error:
            before, after = "before" in q, "after" in q
            if before and not after:
                date_end = min(date_end, boundary) if date_end else boundary
                calendar_boundary = CalendarBoundary(date=boundary, relation="<=")
            elif after and not before:
                start = boundary + timedelta(days=1)
                date_start = max(date_start, start) if date_start else start
                calendar_boundary = CalendarBoundary(date=boundary, relation=">")

    season_type = (
        "playoffs"
        if "playoff" in q or "postseason" in q
        else "play_in"
        if re.search(r"\bplay[-_]in\b", question, re.I)
        or re.search(r"\b(?:the|nba) play in\b|\bplay in (?:tournament|round)\b", q)
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
        None
        if is_record_request(question)
        else "W"
        if re.search(r"\bwins?\b", q)
        else "L"
        if re.search(r"\bloss(?:es)?\b", q)
        else None
    )
    if comparison and re.search(r"\bhome\b", q) and re.search(r"\b(?:road|away)\b", q):
        home_away = None
    if comparison and re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q):
        game_result = None
    if (
        comparison
        and len(re.findall(r"\b(?:last|final|first)\s+\d+\s+games?\b", q)) > 1
        and not player_ids
    ):
        relative_count = None

    candidates = games
    if opponent_id:
        candidates = [
            game for game in candidates if opponent_id in {game.home_team_id, game.away_team_id}
        ]
    if month_comparison:
        candidates = [game for game in candidates if game.game_date.month in named_months]
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
        if game_result == "W":
            candidates = [
                game
                for game in candidates
                if game.status == "final" and scores(game)[0] > scores(game)[1]
            ]
        else:
            candidates = [
                game
                for game in candidates
                if game.status == "final" and scores(game)[0] < scores(game)[1]
            ]
    lead_narrowing = bool(opponent_id and requires_lead_change(question))
    verified_lead_games: list[Game] = []
    unverified_lead_games: list[Game] = []
    if lead_narrowing:
        narrowing = await narrow_by_condition(
            db,
            question,
            candidates,
            record_request=is_record_request(question),
        )
        if narrowing:
            verified_lead_games = narrowing.games
            unverified_lead_games = narrowing.unverified_games
            candidates = [*verified_lead_games, *unverified_lead_games]
    descriptive_reference = bool(
        is_game_score_request(question)
        or (bool(explicit_dates) and not re.search(r"\b(between|from|through|until)\b", q))
        or "overtime game" in q
        or re.search(r"\bgame where\b", q)
        or (
            opponent_id
            and re.search(r"\b(?:the|that|most recent)?\s*game\b", q)
            and "games" not in q
            and not re.search(r"\bper\s+game\b", q)
        )
    )
    all_tied_games = False
    if select_extrema and ("biggest win" in q or "best win" in q) and candidates:
        wins = [g for g in candidates if g.status == "final" and scores(g)[0] > scores(g)[1]]
        maximum = max((scores(g)[0] - scores(g)[1] for g in wins), default=None)
        candidates = [g for g in wins if scores(g)[0] - scores(g)[1] == maximum]
        all_tied_games = True
        descriptive_reference = True
    if select_extrema and "best defensive game" in q and candidates:
        finals = [g for g in candidates if g.status == "final"]
        minimum = min((scores(g)[1] for g in finals), default=None)
        candidates = [g for g in finals if scores(g)[1] == minimum]
        all_tied_games = True
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
    if lead_narrowing and len(candidates) == 1 and not unverified_lead_games:
        resolved_game_ids = [candidates[0].id]
    if relative_count and not player_ids:
        selected = (
            candidates[:relative_count]
            if count_match and "first" in count_match[0]
            else candidates[-relative_count:]
        )
        resolved_game_ids = [game.id for game in selected]
    elif all_tied_games:
        resolved_game_ids = [game.id for game in candidates]
    elif descriptive_reference:
        if "most recent" in q and candidates:
            resolved_game_ids = [candidates[-1].id]
        elif len(candidates) == 1:
            resolved_game_ids = [candidates[0].id]
    elif any((opponent_id, date_start, date_end, season_type, home_away, game_result)):
        resolved_game_ids = [game.id for game in candidates]

    clarification_options = ambiguous_players
    clarification_reason = "ambiguous_player" if ambiguous_players else None
    if lead_narrowing and candidates and (len(candidates) != 1 or unverified_lead_games):
        clarification_reason = (
            "unverified_game_condition" if unverified_lead_games else "ambiguous_game"
        )
        clarification_options = [
            f"{game.game_date}: {game.away_team_id} at {game.home_team_id}"
            for game in verified_lead_games
        ]
        clarification_options.extend(
            f"{game.game_date}: {game.away_team_id} at {game.home_team_id} "
            "(unverified play-by-play score sequence)"
            for game in unverified_lead_games
        )
    elif descriptive_reference and len(candidates) > 1 and not resolved_game_ids:
        clarification_reason = "ambiguous_game"
        clarification_options = [
            f"{game.game_date}: {game.away_team_id} at {game.home_team_id}"
            for game in candidates[:8]
        ]
    if comparison and re.search(r"\b(?:two|2|both)(?: \w+)? games\b", q) and len(candidates) != 2:
        clarification_reason = "ambiguous_game_comparison"
        clarification_options = ["Which two game dates should I compare?"]

    back_to_back = bool(re.search(r"\bback to backs?\b", q))
    specified_leg = bool(
        re.search(r"\b(?:first|second|1st|2nd)\s+(?:night|leg|game)\b", q)
        or re.search(r"\b(?:both games|sweep|sweeps|swept)\b", q)
    )
    if back_to_back and not specified_leg:
        clarification_reason = "undefined_back_to_back_leg"
        clarification_options = [
            "Specify the first leg, the second leg, or winning both games of each back-to-back."
        ]
    elif comparison and re.search(r"\boffen[cs]e\b", q) and re.search(r"\bdefen[cs]e\b", q):
        clarification_reason = "undefined_comparison_metric"
        clarification_options = [
            "Define the offense-versus-defense strength metric and benchmark, "
            "such as a league-relative rating."
        ]
    elif comparison and re.search(r"\boffen[cs]e\b", q) and team_ids:
        clarification_reason = "undefined_comparison_scope"
        clarification_options = [
            "Specify the offense metric and scope: head-to-head Knicks games "
            "or each team's full-season offense."
        ]
    elif comparison and re.search(r"\b(?:league|nba average|other teams)\b", q):
        clarification_reason = "undefined_comparison_scope"
        clarification_options = [
            "Specify the metric, league benchmark, and comparison scope; "
            "ordinary Knicks totals are not a league comparison."
        ]
    elif comparison and re.search(r"\bclose games?\b", q) and re.search(r"\bblowouts?\b", q):
        if not re.search(r"\b(?:threshold|margin|within|at least|more than|under)\s+\d+\b", q):
            clarification_reason = "undefined_comparison_threshold"
            clarification_options = [
                "Define the final-margin threshold for close games and for blowouts "
                "before comparing."
            ]
    if date_error:
        clarification_reason = date_error
        clarification_options = ["Please provide a valid calendar date including the year."]
    elif calendar_error:
        clarification_reason = calendar_error
        clarification_options = ["Please provide the All-Star break boundary date for this season."]

    return ResolvedQuery(
        intent=intent,
        player_ids=player_ids,
        team_ids=team_ids,
        opponent_id=opponent_id,
        game_ids=resolved_game_ids,
        date_start=date_start,
        date_end=date_end,
        calendar_boundary=calendar_boundary,
        relative_game_count=relative_count,
        relative_game_order="first" if count_match and "first" in count_match[0] else "last",
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
