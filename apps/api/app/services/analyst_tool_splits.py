"""get_team_splits handler: team-level situational splits as immutable claims.

The archive can answer home/road, wins/losses, opponent, month, date-window, phase,
back-to-back, close-game and overtime questions from game scores alone. Every bucket
reports its own game count, so a filtered set is never mistaken for the season.

Phase policy: a season-level question is regular season unless it names playoffs or
"overall". Opponent questions always carry an all-phase total plus a phase breakdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services.analyst_split_buckets import (
    _B2B_NOTE,
    _MONTH_GROUPING,
    _OPPONENT_GROUPING,
    _OT_NOTE,
    _PHASE_GROUPING,
    _all_star_break,
    _back_to_back_ids,
    _break_buckets,
    _Bucket,
    _bucket_games,
    _claim_bucket,
    _closeness_buckets,
    _collect_evidence,
    _conference_buckets,
    _conferences,
    _date_side_buckets,
    _location_buckets,
    _month_buckets,
    _month_range,
    _opponent,
    _opponent_buckets,
    _overtime_ids,
    _phase_buckets,
    _phase_games,
    _result_buckets,
    _scope_bucket,
    _window_buckets,
)
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import _MONTHS, ResolvedQuery, team_ids_in_text

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall, VerifiedClaim


@dataclass(frozen=True)
class _Signals:
    months: tuple[int, ...]
    opponents: tuple[str, ...]
    home: bool
    away: bool
    regular: bool
    playoffs: bool
    overall: bool
    wins_word: bool
    losses_word: bool
    first_n: int | None
    last_n: int | None
    before_break: bool
    after_break: bool
    before_date: bool
    after_date: bool
    explicit_range: bool
    close: bool
    blowout: bool
    overtime: bool
    back_to_back: bool
    east: bool
    west: bool
    neutral: bool


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _months_in(q: str) -> tuple[int, ...]:
    found: list[int] = []
    for name, number in _MONTHS.items():
        if name == "may":
            # "may" is far more often a modal verb than a month in this archive.
            if not re.search(r"\b(?:in|during|from|through|since|before|after|of)\s+may\b", q):
                continue
        if re.search(rf"\b{name}\b", q):
            found.append(number)
    return tuple(dict.fromkeys(found))


def _window(q: str, words: str) -> int | None:
    match = re.search(rf"\b(?:{words})\s+(\d+)\s+(?:regular season\s+)?games?\b", q)
    if match:
        return max(1, int(match.group(1)))
    if re.search(rf"\b(?:{words})\s+game\b", q):
        return 1
    return None


def _signals(question: str, scope: ResolvedQuery) -> _Signals:
    q = _norm(question)
    wins_word = bool(re.search(r"\bwins?\b", q))
    losses_word = bool(re.search(r"\bloss(?:es)?\b", q))
    before_date = bool(re.search(r"\bbefore\b", q)) and scope.date_end is not None
    after_date = bool(re.search(r"\b(?:after|since)\b", q)) and scope.date_start is not None
    return _Signals(
        months=_months_in(q),
        opponents=tuple(sorted(team_ids_in_text(question) - {"NYK"})),
        home=bool(re.search(r"\bhome\b", q)),
        away=bool(re.search(r"\b(?:road|away)\b", q)),
        regular="regular season" in q,
        playoffs=bool(re.search(r"\b(?:playoff|postseason)s?\b", q)),
        overall=bool(
            re.search(r"\b(?:overall|all games|all phases|including playoffs|entire season)\b", q)
        ),
        wins_word=wins_word,
        losses_word=losses_word,
        first_n=_window(q, "first|opening"),
        last_n=_window(q, "last|final|previous|past"),
        before_break=bool(
            re.search(r"\b(?:before|pre)\s+(?:the\s+)?all star\b", q) or "before the break" in q
        ),
        after_break=bool(
            re.search(r"\b(?:after|post|since)\s+(?:the\s+)?all star\b", q)
            or "after the break" in q
        ),
        before_date=before_date,
        after_date=after_date,
        explicit_range=bool(re.search(r"\b(?:between|from|through|until)\b", q)),
        close=bool(re.search(r"\b(?:close|closest|tight)\b", q)) or "one possession" in q,
        blowout=bool(re.search(r"\bblowouts?\b", q)),
        overtime=bool(re.search(r"\b(?:ot|overtime|overtimes)\b", q)),
        back_to_back=bool(re.search(r"\bback to backs?\b|\bb2b\b", q)),
        east=bool(re.search(r"\b(?:eastern|east)\b", q)),
        west=bool(re.search(r"\b(?:western|west)\b", q)),
        neutral="neutral" in q,
    )


def _grouping(signals: _Signals) -> str:
    if signals.overtime:
        return "overtime"
    if signals.back_to_back:
        return "back_to_back"
    if signals.close or signals.blowout:
        return "closeness"
    if len(signals.months) >= 2 and not signals.explicit_range:
        return _MONTH_GROUPING
    if signals.opponents:
        return _OPPONENT_GROUPING
    if signals.east and signals.west:
        return "conference"
    if signals.home and signals.away:
        return "location"
    if signals.wins_word and signals.losses_word:
        return "result"
    if signals.regular and signals.playoffs:
        return _PHASE_GROUPING
    if signals.first_n and signals.last_n:
        return "windows"
    if signals.first_n or signals.last_n:
        return "window"
    if signals.before_break or signals.after_break:
        return "break"
    if signals.before_date or signals.after_date:
        return "date_side"
    return "scope"


def _requested_phase(signals: _Signals, scope: ResolvedQuery) -> tuple[str, bool]:
    """Return the phase and whether it was a policy default rather than a request."""
    if signals.overall:
        return "all", False
    if signals.playoffs and not signals.regular:
        return "playoffs", False
    if signals.regular and not signals.playoffs:
        return "regular", False
    if scope.season_type:
        return scope.season_type, False
    return "regular", True


def _scope_label(scope: ResolvedQuery, phase: str, signals: _Signals) -> str:
    parts: list[str] = []
    if scope.home_away == "home":
        parts.append("at home")
    elif scope.home_away == "away":
        parts.append("on the road")
    if scope.opponent_id:
        parts.append(f"vs {scope.opponent_id}")
    if scope.date_start and scope.date_end:
        parts.append(f"{scope.date_start} to {scope.date_end}")
    if not parts:
        parts.append("all games")
    return " ".join(parts)


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    question = tools.question
    signals = _signals(question, scope)
    if signals.neutral:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message=(
                "The release records a home and away team for every game but has no "
                "neutral-site designation, so neutral-site splits cannot be computed."
            ),
            scope={},
        )
    grouping = _grouping(signals)
    phase, defaulted = _requested_phase(signals, scope)
    notes: list[str] = []
    updates: dict[str, Any] = {
        "game_ids": [],
        "relative_game_count": None,
        "game_result": None,
    }
    if grouping == "location":
        updates["home_away"] = None
    if grouping == _PHASE_GROUPING:
        updates["season_type"] = None
    if grouping == _OPPONENT_GROUPING:
        updates["opponent_id"] = None
    if grouping == _MONTH_GROUPING:
        updates["date_start"] = None
        updates["date_end"] = None
    if grouping == "scope" and not any(
        (
            scope.opponent_id,
            scope.date_start,
            scope.date_end,
            scope.home_away,
            scope.season_type,
            scope.relative_game_count,
        )
    ):
        # A descriptive single-game scope is the only filter worth keeping.
        updates.pop("game_ids")
    if len(signals.months) == 1 and grouping != _MONTH_GROUPING and not signals.explicit_range:
        month_range = _month_range(tools.games, signals.months[0])
        if month_range is None:
            return ToolResult(
                status="no_matching_results",
                message="No archived games fall in that month.",
                scope={},
            )
        updates["date_start"], updates["date_end"] = month_range
    if signals.east and not signals.west:
        east_ids = {
            team_id
            for team_id, conference in (
                await _conferences(tools, {_opponent(game) for game in tools.games})
            ).items()
            if conference == "East"
        }
        updates["game_ids"] = [game.id for game in tools.games if _opponent(game) in east_ids]
    if signals.west and not signals.east:
        west_ids = {
            team_id
            for team_id, conference in (
                await _conferences(tools, {_opponent(game) for game in tools.games})
            ).items()
            if conference == "West"
        }
        updates["game_ids"] = [game.id for game in tools.games if _opponent(game) in west_ids]
    base_scope = scope.model_copy(update=updates)
    base_games = sorted(
        tools.selected_games(base_scope), key=lambda game: (game.game_date, game.id)
    )

    break_dates = None
    if signals.before_break or signals.after_break:
        break_dates = _all_star_break(tools)
        if break_dates is None:
            return ToolResult(
                status="unsupported_metric_or_scope",
                message=(
                    "The archive schedule has no All-Star break gap, so a before/after "
                    "break split cannot be derived."
                ),
                scope={},
            )

    buckets: list[_Bucket] = []
    empty_labels: list[tuple[str, str]] = []
    if grouping == _MONTH_GROUPING:
        buckets = _month_buckets(tools, base_games, signals.months, phase, defaulted, notes)
    elif grouping == _OPPONENT_GROUPING:
        buckets = _opponent_buckets(
            tools,
            base_games,
            signals.opponents,
            signals.playoffs,
            signals.regular,
            notes,
        )
    else:
        if grouping == _PHASE_GROUPING:
            phase_games = base_games
        else:
            phase_games, phase = _phase_games(base_games, phase, defaulted, notes)
        if grouping == "location":
            buckets = _location_buckets(phase_games, phase)
            empty_labels = [("home", "home"), ("away", "on the road")]
        elif grouping == "result":
            buckets = _result_buckets(phase_games, phase)
            empty_labels = [("wins", "wins"), ("losses", "losses")]
        elif grouping == _PHASE_GROUPING:
            buckets = _phase_buckets(phase_games)
            empty_labels = [("regular", "regular season"), ("playoffs", "playoffs")]
        elif grouping == "windows":
            buckets = _window_buckets(phase_games, signals.first_n, signals.last_n, phase)
        elif grouping == "window":
            buckets = _window_buckets(phase_games, signals.first_n, signals.last_n, phase)
        elif grouping == "break":
            assert break_dates is not None
            buckets = _break_buckets(
                phase_games,
                break_dates,
                signals.before_break,
                signals.after_break,
                phase,
            )
            empty_labels = []
            if signals.before_break:
                empty_labels.append(("before_break", "before the All-Star break"))
            if signals.after_break:
                empty_labels.append(("after_break", "after the All-Star break"))
        elif grouping == "date_side":
            buckets = _date_side_buckets(
                phase_games,
                scope,
                signals.before_date,
                signals.after_date,
                phase,
            )
        elif grouping == "overtime":
            overtime = await _overtime_ids(tools, phase_games)
            buckets = [
                bucket
                for bucket in (
                    _bucket_games(
                        [game for game in phase_games if game.id in overtime],
                        "overtime",
                        "in overtime games",
                        phase,
                        limitations=[_OT_NOTE],
                    ),
                )
                if bucket.games
            ]
        elif grouping == "back_to_back":
            back_to_back = _back_to_back_ids(tools)
            buckets = [
                bucket
                for bucket in (
                    _bucket_games(
                        [game for game in phase_games if game.id in back_to_back],
                        "back_to_back",
                        "in back-to-backs",
                        phase,
                        limitations=[_B2B_NOTE],
                    ),
                )
                if bucket.games
            ]
        elif grouping == "closeness":
            buckets = _closeness_buckets(phase_games, signals.close, signals.blowout, phase)
        elif grouping == "conference":
            conferences = await _conferences(tools, {_opponent(game) for game in phase_games})
            buckets = _conference_buckets(phase_games, conferences, phase)
            empty_labels = [
                ("conference:East", "Eastern teams"),
                ("conference:West", "Western teams"),
            ]
        else:
            label = _scope_label(scope, phase, signals)
            buckets = _scope_bucket(phase_games, scope, phase, label)

    if not buckets:
        message = (
            "No archived games match this scope; this is not evidence that no such games occurred."
        )
        if any(
            (
                signals.overtime,
                signals.back_to_back,
                signals.close,
                signals.blowout,
            )
        ):
            message = (
                "No archived games match this requested split; this is not evidence "
                "that no such games occurred."
            )
        return ToolResult(
            status="no_matching_results",
            message=message,
            scope={},
        )

    claims: list[VerifiedClaim] = []
    for bucket in buckets:
        claims.append(_claim_bucket(tools, scope, bucket, notes))

    present = {bucket.key for bucket in buckets}
    missing = [label for key, label in empty_labels if key not in present]
    status = "incomplete_coverage" if missing else "ok"
    message = (
        "Calculated from all applicable archived games; every bucket reports its own denominator."
        if status == "ok"
        else f"Missing requested buckets: {', '.join(missing)}."
    )
    return ToolResult(
        status=status,
        message=message,
        claims=claims,
        evidence=_collect_evidence(tools, claims),
        scope={},
    )
