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
from app.services.query_comparison_specs import (
    MONTH_LABELS,
    MONTH_NAMES,
    ComparisonResolution,
    ComparisonSpec,
    WindowSpec,
)
from app.services.query_comparison_windows import (
    single_opponent_premise,
    single_window,
)
from app.services.query_comparisons import all_star_break, resolve_comparison
from app.services.query_operation_decisions import classify_operation
from app.services.query_operations import (
    Operation,
    RequestedAggregation,
    RequestedMeasure,
    ThresholdSpec,
    is_record_request,
    normalize_text,
    player_stat,
    requested_aggregation,
)
from app.services.query_players import name_candidates, resolve_player_mentions
from app.services.query_scope_parsing import (
    INTERVAL_WORDING,
    _metric,
    _month_day_dates,
    _month_interval,
    _named_year,
    _periods,
    games_in_scope,
)
from app.services.team_aliases import team_ids_in_text
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
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
    periods: list[int] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    metric: str | None = None
    relative_game_position: Literal["first", "last"] | None = None
    # Every measure the question itself asks for, in the order it asks for them. A
    # compound ask keeps all of them instead of delivering whichever matched first.
    requested_measures: tuple[RequestedMeasure, ...] = Field(default_factory=tuple)
    aggregation: RequestedAggregation | None = None
    comparison: ComparisonSpec | None = None
    operation: Operation | None = None
    operation_reason: str | None = None
    threshold: ThresholdSpec | None = None
    stat: str | None = None
    requires_clarification: bool = False
    clarification_reason: str | None = None
    clarification_question: str | None = None
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


UNSUPPORTED_OPERATION = (
    "This archive answers records, win and loss counts, season totals and averages, "
    "largest win and loss margins, losing and winning streaks, and score-margin swings; "
    "it cannot answer that specific ranking."
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
    player_ids, ambiguous_players = resolve_player_mentions(
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
        for candidate in name_candidates(question):
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
            player_ids, ambiguous_players = resolve_player_mentions(
                question,
                list(proposed.values()),
                typo_threshold=typo_threshold,
            )

    q = normalize_text(question)
    team_ids = sorted(team_ids_in_text(question) - {"NYK"})
    opponent_id = team_ids[0] if len(team_ids) == 1 else None
    explicit_dates = [
        date.fromisoformat(value) for value in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", question)
    ]
    date_start = explicit_dates[0] if explicit_dates else None
    date_end = explicit_dates[-1] if explicit_dates else None
    latest_date = games[-1].game_date if games else None
    relative_count: int | None = None
    relative_position: Literal["first", "last"] | None = None
    window = single_window(q)
    if window is not None:
        relative_count, relative_position = window.count, window.position
    elif re.search(r"\b(?:last|previous)\s+game\b", q):
        window = WindowSpec(position="last", count=1)
        relative_count, relative_position = window.count, window.position

    named_months = sorted(
        {month for name, month in MONTH_NAMES.items() if re.search(rf"\b{name}\b", q)}
    )
    named_year = _named_year(q)
    month_days = _month_day_dates(q, games)
    if latest_date and "this month" in q:
        date_start = latest_date.replace(day=1)
        date_end = latest_date
    elif month_days:
        # A named month with day endpoints is an explicit interval, not the whole month.
        date_start, date_end = min(month_days), max(month_days)
    elif len(named_months) > 1 and re.search(
        r"\b(?:between|from|through|thru|until|till|since)\b", q
    ):
        # "From January through March" is one calendar interval, not two groupings.
        date_start, date_end = _month_interval(named_months, named_year, games, q, latest_date)
    elif len(named_months) == 1 and games:
        named_month = named_months[0]
        month_dates = [
            game.game_date
            for game in games
            if game.game_date.month == named_month
            and (named_year is None or game.game_date.year == named_year)
        ]
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
        if re.search(r"\bplay in (?:tournament|games?)\b", q) or "play-in" in question.lower()
        else "regular"
        if "regular season" in q
        else None
    )
    break_before, break_after = all_star_break(games)
    if "all star" in q and break_before and break_after:
        if re.search(r"\bafter\b", q) and not re.search(r"\bbefore\b", q):
            date_start, date_end = break_after, None
        elif re.search(r"\bbefore\b", q) and not re.search(r"\bafter\b", q):
            date_start, date_end = None, break_before

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

    periods = _periods(question)
    metric = _metric(question)
    comparison = resolve_comparison(
        question,
        opponents=tuple(team_ids),
        has_player=bool(player_ids),
        metric=metric,
        games=games,
        stat=player_stat(question),
        aggregation=requested_aggregation(question),
        date_start=date_start,
        date_end=date_end,
        season_type=season_type,
        home_away=home_away,
        game_result=game_result,
        window=window,
    )
    if comparison.spec is not None:
        # Each typed group owns one axis. Only the constraints no group owns stay on the
        # scope, so "against Boston in January" keeps bounding both groups while the
        # split field itself is cleared instead of collapsing them.
        shared = comparison.spec.filters
        opponent_id = shared.opponent_id
        home_away = shared.home_away
        game_result = shared.game_result
        date_start, date_end = shared.date_start, shared.date_end
        relative_count = relative_position = None
    candidates = games_in_scope(
        games,
        opponent_id=opponent_id,
        dates=() if INTERVAL_WORDING.search(q) else tuple(explicit_dates),
        season_type=season_type,
        home_away=home_away,
        date_start=date_start,
        date_end=date_end,
        game_result=game_result,
    )
    # A stated game count is a premise about the population the request itself narrowed,
    # so it is counted after the date, venue, phase and result filters, never over the
    # whole release.
    premise = single_opponent_premise(question, opponents=tuple(team_ids), games=candidates)

    descriptive_reference = bool(
        (bool(explicit_dates) and not INTERVAL_WORDING.search(q))
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
    if comparison.spec is not None:
        resolved_game_ids = []
    elif relative_count == 1 and candidates:
        # A one-game window is that game. A longer window is a property of the filtered
        # population, applied once where the population is read; pre-selecting its tail
        # here is what turned a first-N ask into the last games.
        resolved_game_ids = [candidates[-1 if relative_position == "last" else 0].id]
    elif descriptive_reference:
        if "most recent" in q and candidates:
            resolved_game_ids = [candidates[-1].id]
        elif len(candidates) == 1:
            resolved_game_ids = [candidates[0].id]
    elif any((opponent_id, date_start, date_end, season_type, home_away, game_result)):
        resolved_game_ids = [game.id for game in candidates]

    clarification_options = ambiguous_players
    clarification_reason = "ambiguous_player" if ambiguous_players else None
    clarification_question = "Which Knicks player did you mean?" if ambiguous_players else None
    decision = classify_operation(
        question,
        has_player=bool(player_ids),
        ambiguous_player=bool(ambiguous_players),
        periods=tuple(periods),
        metric=metric,
        performance_scope=(
            "game"
            if comparison.spec is None and len(resolved_game_ids) == 1
            else "population"
            if comparison.spec is not None
            or resolved_game_ids
            or relative_count
            or re.search(r"\b(?:season|archive)\b", q)
            else "unspecified"
        ),
    )
    if decision.reason is not None:
        # A live or unsupported ask refuses even when it names two populations.
        comparison = ComparisonResolution()
    # A named year the release does not cover, or several months named without a
    # comparison, is not a silent whole-month or whole-release fallback.
    missing_year = named_year is not None and not any(
        game.game_date.year == named_year for game in games
    )
    ambiguous_months = (
        len(named_months) > 1
        and comparison.spec is None
        and not month_days
        and not re.search(r"\b(?:between|from|through|thru|until|till|since)\b", q)
    )
    if missing_year and clarification_reason is None:
        clarification_reason = "outside_archive"
        clarification_question = (
            f"The archive covers {resolved_version}; it has no games in {named_year}. "
            "Which archived dates should I use instead?"
        )
        clarification_options = []
    elif ambiguous_months and clarification_reason is None:
        labels = " and ".join(MONTH_LABELS[month] for month in named_months)
        first, last = MONTH_LABELS[named_months[0]], MONTH_LABELS[named_months[-1]]
        clarification_reason = "ambiguous_interval"
        clarification_question = (
            f"You named {labels}. Should I treat them as one interval or compare them?"
        )
        clarification_options = [f"one interval: {first} through {last}", f"compare {labels}"]
    elif descriptive_reference and len(candidates) > 1 and not resolved_game_ids:
        if premise.clarification and clarification_reason is None:
            clarification_reason = "premise_conflict"
            clarification_question = premise.clarification
            clarification_options = list(premise.options)
        else:
            clarification_reason = "ambiguous_game"
            clarification_options = [
                f"{game.game_date}: {game.away_team_id} at {game.home_team_id}"
                for game in candidates[:8]
            ]
    elif premise.clarification and clarification_reason is None:
        clarification_reason = "premise_conflict"
        clarification_question = premise.clarification
        clarification_options = list(premise.options)
    elif decision.clarification and clarification_reason is None and comparison.spec is None:
        # The ask is answerable once one measurement is named; never refuse it for a word.
        clarification_reason = "ambiguous_metric"
        clarification_question = decision.clarification
        clarification_options = list(decision.options)
    if decision.reason is not None:
        clarification_reason = clarification_question = None
        clarification_options = []

    return ResolvedQuery(
        intent=intent,
        player_ids=player_ids,
        team_ids=team_ids,
        opponent_id=opponent_id,
        game_ids=resolved_game_ids,
        date_start=date_start,
        date_end=date_end,
        relative_game_count=relative_count,
        relative_game_position=relative_position,
        comparison=comparison.spec,
        periods=periods,
        season_type=season_type,
        home_away=home_away,
        game_result=game_result,
        metric=metric,
        requested_measures=decision.measures,
        aggregation=decision.aggregation,
        operation=decision.operation,
        operation_reason=decision.reason,
        threshold=decision.threshold,
        stat=decision.stat,
        requires_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
        clarification_question=clarification_question,
        clarification_options=clarification_options,
        data_version=resolved_version,
    )
