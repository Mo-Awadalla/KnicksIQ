"""Team split buckets and their immutable claims.

This module owns the bucket definitions for get_team_splits: which games belong to a
home/road, result, phase, month, opponent, window, break, closeness, conference or
overtime bucket, and how one bucket becomes a VerifiedClaim. The handler in
analyst_tool_splits.py decides which buckets a question asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from app.models.box_score import PeriodScore
from app.models.team import Team
from app.services.query_resolution import _MONTHS, ResolvedQuery
from sqlalchemy import select

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import Evidence, VerifiedClaim


_PHASE_LABELS = {"regular": "regular season", "playoffs": "playoffs", "play_in": "play-in"}
_ALL_PHASES = "all phases"
_NEUTRAL_NOTE = "No neutral-site flag; home is the recorded home team."
_TIE_NOTE = "Tied finals excluded."
_OT_NOTE = "Each overtime game is counted once."
_B2B_NOTE = "Second game on consecutive dates."
_CLOSE_NOTE = "Close: margin <= 5; blowout: margin >= 10."
_PHASE_GROUPING = "phase"
_OPPONENT_GROUPING = "opponents"
_MONTH_GROUPING = "months"


@dataclass(frozen=True)
class _Bucket:
    key: str
    label: str
    games: tuple[Game, ...]
    season_type: str | None
    filters: dict[str, Any]
    limitations: tuple[str, ...] = ()


def _phase_label(season_type: str | None) -> str:
    return _ALL_PHASES if season_type is None else _PHASE_LABELS.get(season_type, season_type)


def _filter_phase(games: list[Game], phase: str) -> list[Game]:
    if phase == "all":
        return games
    return [game for game in games if game.season_type == phase]


def _decided(games: list[Game]) -> tuple[list[Game], int]:
    decided = [
        game for game in games if game.status == "final" and game.home_score != game.away_score
    ]
    return decided, len(games) - len(decided)


def _phase_games(
    games: list[Game], phase: str, defaulted: bool, notes: list[str]
) -> tuple[list[Game], str]:
    filtered = _filter_phase(games, phase)
    if not filtered and defaulted and games:
        notes.append(f"No {_phase_label(phase)} games in this window; using all phases.")
        return games, "all"
    return filtered, phase


def _score(game: Game) -> tuple[int, int]:
    return (
        (game.home_score, game.away_score)
        if game.home_team_id == "NYK"
        else (game.away_score, game.home_score)
    )


def _opponent(game: Game) -> str:
    return game.away_team_id if game.home_team_id == "NYK" else game.home_team_id


def _margin(game: Game) -> int:
    return abs(game.home_score - game.away_score)


def _month_range(games: list[Game], month: int) -> tuple[date, date] | None:
    dates = [game.game_date for game in games if game.game_date.month == month]
    return (min(dates), max(dates)) if dates else None


def _all_star_break(tools: AnalystTools) -> tuple[date, date] | None:
    regular = sorted({game.game_date for game in tools.games if game.season_type == "regular"})
    if not regular:
        return None
    year = max(regular).year
    window = [day for day in regular if day.year == year and 1 <= day.month <= 3]
    gaps = [
        (after - before, before, after) for before, after in zip(window, window[1:], strict=False)
    ]
    if not gaps:
        return None
    gap, before, after = max(gaps)
    # Normal scheduling gaps are two to four days; the All-Star break is longer.
    return (before, after) if gap.days >= 5 else None


def _back_to_back_ids(tools: AnalystTools) -> set[int]:
    dates = {game.game_date for game in tools.games}
    return {game.id for game in tools.games if game.game_date - timedelta(days=1) in dates}


async def _overtime_ids(tools: AnalystTools, games: list[Game]) -> set[int]:
    game_ids = [game.id for game in games]
    if not game_ids:
        return set()
    statement = (
        select(PeriodScore.game_id)
        .where(
            PeriodScore.release_id == tools.release.id,
            PeriodScore.game_id.in_(game_ids),
            PeriodScore.period > 4,
        )
        .distinct()
    )
    return set((await tools.db.execute(statement)).scalars())


async def _conferences(tools: AnalystTools, team_ids: set[str]) -> dict[str, str | None]:
    if not team_ids:
        return {}
    statement = select(Team.id, Team.conference).where(Team.id.in_(team_ids))
    return {
        team_id: conference for team_id, conference in (await tools.db.execute(statement)).all()
    }


def _context_label(scope: ResolvedQuery) -> str:
    parts: list[str] = []
    if scope.home_away == "home":
        parts.append("at home")
    elif scope.home_away == "away":
        parts.append("on the road")
    return " ".join(parts)


def _bucket_games(
    games: list[Game],
    key: str,
    label: str,
    season_type: str | None,
    limitations: tuple[str, ...] | list[str] = (),
    **filters: Any,
) -> _Bucket:
    decided, excluded = _decided(games)
    notes = list(limitations)
    if excluded:
        notes.append(_TIE_NOTE)
    return _Bucket(
        key=key,
        label=label,
        games=tuple(decided),
        season_type=season_type,
        filters=filters,
        limitations=tuple(notes),
    )


def _location_buckets(games: list[Game], phase: str) -> list[_Bucket]:
    home = [game for game in games if game.home_team_id == "NYK"]
    away = [game for game in games if game.away_team_id == "NYK"]
    buckets = [
        _bucket_games(
            home,
            "home",
            "home",
            phase,
            home_away="home",
            limitations=[_NEUTRAL_NOTE],
        ),
        _bucket_games(
            away,
            "away",
            "on the road",
            phase,
            home_away="away",
            limitations=[_NEUTRAL_NOTE],
        ),
    ]
    return [bucket for bucket in buckets if bucket.games]


def _result_buckets(games: list[Game], phase: str) -> list[_Bucket]:
    wins = [game for game in games if _score(game)[0] > _score(game)[1]]
    losses = [game for game in games if _score(game)[0] < _score(game)[1]]
    return [
        bucket
        for bucket in (
            _bucket_games(wins, "wins", "in wins", phase, game_result="W"),
            _bucket_games(losses, "losses", "in losses", phase, game_result="L"),
        )
        if bucket.games
    ]


def _phase_buckets(games: list[Game]) -> list[_Bucket]:
    return [
        bucket
        for bucket in (
            _bucket_games(
                [game for game in games if game.season_type == "regular"],
                "regular",
                "regular season",
                "regular",
            ),
            _bucket_games(
                [game for game in games if game.season_type == "playoffs"],
                "playoffs",
                "playoffs",
                "playoffs",
            ),
        )
        if bucket.games
    ]


def _month_buckets(
    tools: AnalystTools,
    games: list[Game],
    months: tuple[int, ...],
    phase: str,
    defaulted: bool,
    notes: list[str],
) -> list[_Bucket]:
    buckets: list[_Bucket] = []
    for month in months:
        month_games = [game for game in games if game.game_date.month == month]
        if not month_games:
            notes.append(f"No archived games in month {month}.")
            continue
        phase_games, phase_used = _phase_games(month_games, phase, defaulted, notes)
        year = month_games[0].game_date.year
        label = f"{next(name for name, value in _MONTHS.items() if value == month).title()} {year}"
        bucket = _bucket_games(
            phase_games,
            f"month:{year}-{month:02d}",
            label,
            None if phase_used == "all" else phase_used,
        )
        if bucket.games:
            buckets.append(bucket)
    return buckets


def _opponent_buckets(
    tools: AnalystTools,
    games: list[Game],
    opponents: tuple[str, ...],
    playoffs: bool,
    regular: bool,
    notes: list[str],
) -> list[_Bucket]:
    buckets: list[_Bucket] = []
    for opponent in opponents:
        opponent_games = [game for game in games if _opponent(game) == opponent]
        if not opponent_games:
            notes.append(f"No archived games against {opponent} match this scope.")
            continue
        if playoffs and not regular:
            phases: tuple[str, ...] = ("playoffs",)
        elif regular and not playoffs:
            phases = ("regular",)
        else:
            phases = ("all", "regular", "playoffs")
        for phase in phases:
            if phase == "all":
                selected = opponent_games
            else:
                selected = [game for game in opponent_games if game.season_type == phase]
            label = f"vs {opponent}"
            bucket = _bucket_games(
                selected,
                f"opponent:{opponent}:{phase}",
                label,
                None if phase == "all" else phase,
                opponent_id=opponent,
            )
            if bucket.games:
                buckets.append(bucket)
    return buckets


def _window_buckets(
    games: list[Game], first_n: int | None, last_n: int | None, phase: str
) -> list[_Bucket]:
    buckets: list[_Bucket] = []
    if first_n:
        bucket = _bucket_games(
            games[:first_n], f"window:first:{first_n}", f"first {first_n} games", phase
        )
        if bucket.games:
            buckets.append(bucket)
    if last_n:
        bucket = _bucket_games(
            games[-last_n:], f"window:last:{last_n}", f"last {last_n} games", phase
        )
        if bucket.games:
            buckets.append(bucket)
    return buckets


def _break_buckets(
    games: list[Game],
    break_dates: tuple[date, date],
    before_requested: bool,
    after_requested: bool,
    phase: str,
) -> list[_Bucket]:
    before, after = break_dates
    buckets: list[_Bucket] = []
    if before_requested:
        bucket = _bucket_games(
            [game for game in games if game.game_date <= before],
            "before_break",
            "before the All-Star break",
            phase,
        )
        if bucket.games:
            buckets.append(bucket)
    if after_requested:
        bucket = _bucket_games(
            [game for game in games if game.game_date >= after],
            "after_break",
            "after the All-Star break",
            phase,
        )
        if bucket.games:
            buckets.append(bucket)
    return buckets


def _date_side_buckets(
    games: list[Game],
    scope: ResolvedQuery,
    before_requested: bool,
    after_requested: bool,
    phase: str,
) -> list[_Bucket]:
    buckets: list[_Bucket] = []
    if before_requested and scope.date_end:
        bucket = _bucket_games(games, f"before:{scope.date_end}", f"before {scope.date_end}", phase)
        if bucket.games:
            buckets.append(bucket)
    if after_requested and scope.date_start:
        bucket = _bucket_games(
            games, f"after:{scope.date_start}", f"since {scope.date_start}", phase
        )
        if bucket.games:
            buckets.append(bucket)
    return buckets


def _closeness_buckets(
    games: list[Game], close_requested: bool, blowout_requested: bool, phase: str
) -> list[_Bucket]:
    close = [game for game in games if _margin(game) <= 5]
    middle = [game for game in games if 6 <= _margin(game) <= 9]
    blowout = [game for game in games if _margin(game) >= 10]
    buckets: list[_Bucket] = []
    if close_requested:
        bucket = _bucket_games(close, "close", "in close games", phase, limitations=[_CLOSE_NOTE])
        if bucket.games:
            buckets.append(bucket)
    if close_requested and blowout_requested and middle:
        buckets.append(
            _bucket_games(
                middle,
                "middle",
                "in games decided by 6 to 9",
                phase,
                limitations=["Neither close nor a blowout under the stated cutoffs."],
            )
        )
    if blowout_requested:
        bucket = _bucket_games(blowout, "blowout", "in blowouts", phase, limitations=[_CLOSE_NOTE])
        if bucket.games:
            buckets.append(bucket)
    return buckets


def _conference_buckets(
    games: list[Game], conferences: dict[str, str | None], phase: str
) -> list[_Bucket]:
    east = [game for game in games if conferences.get(_opponent(game)) == "East"]
    west = [game for game in games if conferences.get(_opponent(game)) == "West"]
    unknown = [game for game in games if _opponent(game) not in conferences]
    buckets = [
        bucket
        for bucket in (
            _bucket_games(east, "conference:East", "against Eastern teams", phase),
            _bucket_games(west, "conference:West", "against Western teams", phase),
        )
        if bucket.games
    ]
    if unknown:
        buckets.append(
            _bucket_games(
                unknown,
                "conference:unknown",
                "against teams with no conference",
                phase,
                limitations=["Opponent conference is missing from the teams table."],
            )
        )
    return buckets


def _scope_bucket(games: list[Game], scope: ResolvedQuery, phase: str, label: str) -> list[_Bucket]:
    bucket = _bucket_games(
        games,
        "scope",
        label,
        None if phase == "all" else phase,
        home_away=scope.home_away,
        opponent_id=scope.opponent_id,
    )
    return [bucket] if bucket.games else []


def _claim_bucket(
    tools: AnalystTools, scope: ResolvedQuery, bucket: _Bucket, notes: list[str]
) -> VerifiedClaim:
    games = list(bucket.games)
    count = len(games)
    points_for = sum(_score(game)[0] for game in games)
    points_against = sum(_score(game)[1] for game in games)
    wins = sum(_score(game)[0] > _score(game)[1] for game in games)
    value = {
        "games": count,
        "wins": wins,
        "losses": count - wins,
        "points_for_per_game": round(points_for / count, 2),
        "points_against_per_game": round(points_against / count, 2),
        "margin_per_game": round((points_for - points_against) / count, 2),
    }
    limitations = list(bucket.limitations) + list(notes)
    statement = (
        f"Knicks {bucket.label}, {_phase_label(bucket.season_type)}: "
        f"{wins}-{count - wins} in {count} games; "
        f"{value['points_for_per_game']:.2f} for, "
        f"{value['points_against_per_game']:.2f} against, "
        f"{value['margin_per_game']:+.2f} margin per game."
    )
    claim_scope = scope.model_copy(update=bucket.filters)
    if bucket.season_type:
        claim_scope = claim_scope.model_copy(update={"season_type": bucket.season_type})
    return tools.claim(
        subject="team:NYK",
        metric=f"team_splits:{bucket.key}",
        value=value,
        unit="record, per-game",
        games=games,
        evidence=[tools.receipt(game) for game in games],
        statement=statement,
        scope=claim_scope,
        sample=count,
        denominator=count,
        limitations=limitations,
        eligibility={"game": "final"},
        window=None,
        population="Knicks games",
    )


def _collect_evidence(tools: AnalystTools, claims: list[VerifiedClaim]) -> list[Evidence]:
    evidence: dict[str, Evidence] = {}
    for claim in claims:
        for reference in claim.supporting_evidence_ids:
            if reference in tools.evidence:
                evidence[reference] = tools.evidence[reference]
    return list(evidence.values())
