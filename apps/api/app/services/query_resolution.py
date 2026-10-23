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
from app.services.query_dates import (
    _MONTH_ALIASES,
    MONTH_WORDS,
    date_window,
)
from app.services.query_game_scope import (
    InheritedScope,
    names_season_scope,
    referenced_game,
)
from app.services.query_names import (
    _name_candidates,
    unique_given_names,
)
from app.services.query_names import (
    resolve_player_mentions as _resolve_player_mentions,
)
from app.services.query_parsing import _explicit_dates
from app.services.query_policy import (
    Phase,
    SeasonType,
    is_outcome_subset,
    names_phase,
    resolve_phase,
)
from app.services.query_text import (
    METRIC_WORDS,
    aggregations_in_text,
    is_explanation,
    is_game_score_request,
    is_record_request,
    metrics_in_text,
    normalize,
    periods_in_text,
    without_period_phrases,
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
    # "First 10 games" counts from the start of the scope; "last 10" from the end.
    relative_from_start: bool = False
    relative_game_order: Literal["first", "last"] = "last"
    periods: list[int] = Field(default_factory=list)
    season_type: Literal["regular", "play_in", "playoffs"] | None = None
    # The user asked for every phase; distinguishes None from "unspecified" for merges.
    all_phases: bool = False
    home_away: Literal["home", "away"] | None = None
    game_result: Literal["W", "L"] | None = None
    metric: str | None = None
    aggregation: Literal["average", "total"] | None = None
    requested_metrics: list[str] = Field(default_factory=list)
    requested_aggregations: list[Literal["average", "total"]] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_reason: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    data_version: str

    def _first_window(self) -> bool:
        return self.relative_from_start or self.relative_game_order == "first"

    def window[T](self, ordered: list[T]) -> list[T]:
        """Apply the relative game window to a chronologically ordered list."""
        count = self.relative_game_count
        if not count:
            return ordered
        return ordered[:count] if self._first_window() else ordered[-count:]

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
                relative_game_order="first" if self._first_window() else "last",
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
    default_season_type: SeasonType | None = None,
    default_all_phases: bool = False,
    inherit: InheritedScope | None = None,
    select_extrema: bool = True,
) -> ResolvedQuery:
    """Resolve canonical entities and filters without model inference.

    ``inherit`` supplies the previous accepted turn's scope and topic as the default
    values for everything this question does not name, before candidate selection, so
    the resolved game ids and phase stay consistent with each other. Narrative
    computation retains the comparison population with ``select_extrema=False``;
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
        unique_givens=unique_given_names(players),
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
    main_dates, date_error = _explicit_dates(question, games)
    if date_error:
        explicit_dates = []
        date_start = date_end = None
    elif "christmas day" in q and main_dates:
        explicit_dates = main_dates
        date_start = date_end = main_dates[0]
    elif (
        main_dates
        and not window.dates
        and not re.search(r"\b(?:to|through|thru|until|between|from)\b", q)
    ):
        # Named days without a range connector are that day's games, not the span
        # between them (for example "January 10 and January 20").
        explicit_dates = main_dates
        date_start, date_end = min(main_dates), max(main_dates)

    named_months = {month for name, month in _MONTH_ALIASES.items() if re.search(rf"\b{name}\b", q)}
    comparison = bool(
        re.search(r"\b(?:compare|comparison|versus|vs|better|stronger)\b", q)
        or re.search(r"\b(?:home or away|eastern or western)\b", q)
    )
    month_comparison = comparison and len(named_months) > 1 and not explicit_dates
    if month_comparison:
        # A comparison needs every requested month, not the first named one.
        month_dates = [game.game_date for game in games if game.game_date.month in named_months]
        if month_dates:
            first, last = min(month_dates), max(month_dates)
            date_start = first.replace(day=1)
            date_end = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    if (
        comparison
        and len(re.findall(r"\b(?:last|final|first)\s+\d+\s+games?\b", q)) > 1
        and not player_ids
    ):
        relative_count = None
        relative_from_start = False

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

    named_phase = names_phase(question)
    named_site = (
        "home"
        if re.search(r"\bhome\b", q)
        else "away"
        if re.search(r"\b(?:road|away)\b", q)
        else None
    )
    # A follow-up that names the season asks for the season population: the inherited
    # game/date window is replaced while the topic's subject and metric survive.
    season_scope = inherit is not None and not named_phase and names_season_scope(question)
    reference = referenced_game(question, inherit, games)
    named_window = bool(
        window.explicit
        or explicit_dates
        or reference
        or season_scope
        or month_comparison
        or "all star" in q
        or date_error
    )
    # Game ids are the prior window's output, not an input: they may bound an elliptical
    # turn only when it names no opponent, site or outcome of its own.
    inherited_games: list[int] = []
    if reference:
        # A deictic game reference names the whole window, not only one filter.
        date_start = date_end = reference.game_date
        relative_count = None
        relative_from_start = False
    elif season_scope:
        date_start = date_end = None
        relative_count = None
        relative_from_start = False
    elif inherit is not None and not named_window and not named_phase:
        relative_count = inherit.relative_game_count
        relative_from_start = inherit.relative_from_start or inherit.relative_game_order == "first"
        date_start = inherit.date_start
        date_end = inherit.date_end
        if not team_ids and named_site is None and not is_outcome_subset(question):
            inherited_games = inherit.game_ids
    season_level = not (opponent_id or explicit_dates or relative_count or date_start or date_end)
    if season_scope:
        phase = Phase(
            named=True,
            season_type=(inherit.season_type if inherit is not None else None) or "regular",
            all_phases=False,
        )
    elif inherit is not None and not named_phase:
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
    else:
        wins = bool(re.search(r"\bwins?\b|\bwon\b|\bwinning\b", q))
        losses = bool(re.search(r"\bloss(?:es)?\b|\blost\b|\blosing\b", q))
        if wins and not losses:
            game_result = "W"
        elif losses and not wins:
            game_result = "L"
        elif wins and losses:
            game_result = None
        else:
            game_result = inherit.game_result if inherit else None
    if comparison and re.search(r"\bhome\b", q) and re.search(r"\b(?:road|away)\b", q):
        home_away = None
    if comparison and re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q):
        game_result = None

    if player_ids or ambiguous_players:
        resolved_player_ids = player_ids
    elif inherit is not None:
        resolved_player_ids = inherit.player_ids
    else:
        resolved_player_ids = []
    periods = periods_in_text(question)
    if not periods and inherit is not None:
        periods = inherit.periods
    named_metrics = metrics_in_text(question)
    if is_record_request(question) or is_explanation(question):
        named_metrics = set()
    elif not named_metrics and inherit is not None:
        named_metrics = set(inherit.requested_metrics) or (
            {inherit.metric} if inherit.metric else set()
        )
    metric = next(iter(named_metrics)) if len(named_metrics) == 1 else None
    named_aggregations = aggregations_in_text(question)
    if not named_aggregations and inherit is not None:
        named_aggregations = set(inherit.requested_aggregations) or (
            {inherit.aggregation} if inherit.aggregation else set()
        )
    aggregation = next(iter(named_aggregations)) if len(named_aggregations) == 1 else None

    candidates = [reference] if reference else games
    if inherited_games:
        inherited_ids = set(inherited_games)
        candidates = [game for game in candidates if game.id in inherited_ids]
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
    if game_result == "W":
        candidates = [
            game
            for game in candidates
            if game.status == "final" and scores(game)[0] > scores(game)[1]
        ]
    elif game_result == "L":
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
    if reference:
        resolved_game_ids = [reference.id]
    elif relative_count and not resolved_player_ids:
        selected = (
            candidates[:relative_count] if relative_from_start else candidates[-relative_count:]
        )
        resolved_game_ids = [game.id for game in selected]
    elif inherited_games:
        resolved_game_ids = [game.id for game in candidates]
    elif lead_narrowing and len(candidates) == 1 and not unverified_lead_games:
        resolved_game_ids = [candidates[0].id]
    elif all_tied_games:
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
        player_ids=resolved_player_ids,
        team_ids=team_ids,
        opponent_id=opponent_id,
        game_ids=resolved_game_ids,
        date_start=date_start,
        date_end=date_end,
        calendar_boundary=calendar_boundary,
        relative_game_count=relative_count,
        relative_from_start=bool(relative_count) and relative_from_start,
        relative_game_order="first" if relative_count and relative_from_start else "last",
        periods=periods,
        season_type=season_type,
        all_phases=phase.all_phases,
        home_away=home_away,
        game_result=game_result,
        metric=metric,
        aggregation=aggregation,
        requested_metrics=sorted(named_metrics),
        requested_aggregations=sorted(named_aggregations),
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
        for word in without_period_phrases(phrase).split()
        if not word.isdigit()
        and word not in _SCOPE_WORDS
        and word not in METRIC_WORDS
        and word not in MONTH_WORDS
    }
    return not leftover
