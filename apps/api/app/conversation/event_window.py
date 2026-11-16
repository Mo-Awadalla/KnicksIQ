from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.analyst_citations import requested_sources
from app.services.analyst_dispatch import season_matches
from app.services.analyst_provenance import event_projection, row_receipt
from app.services.archive_clock import GameMoment, moment_from_question
from app.services.evidence_contracts import Evidence, ToolResult
from sqlalchemy import select
from sqlalchemy.orm import joinedload

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

_DURATION = re.compile(
    r"\b(first|opening|last|final|closing)\s+"
    r"(?:(one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+)?"
    r"(minutes?|mins?|seconds?|secs?)\b",
    re.IGNORECASE,
)
_NUMBERS = {
    word: number
    for number, word in enumerate(
        ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 1
    )
}


def _seconds(event: GameEvent) -> int | None:
    try:
        minutes, seconds = map(int, event.clock.split(":"))
        if not 0 <= seconds < 60 or minutes < 0:
            return None
        return GameMoment(event.period, minutes * 60 + seconds).seconds_remaining
    except (TypeError, ValueError):
        return None


def _event_statement(row: dict[str, object], game: Game) -> str:
    period_value = row["period"]
    if not isinstance(period_value, int):
        raise ValueError("Event period must be an integer")
    period = period_value
    period_name = f"Q{period}" if period <= 4 else "OT" if period == 5 else f"{period - 4}OT"
    statement = (
        f"{game.game_date} {game.away_team_id} at {game.home_team_id}: "
        f"{period_name} {row['clock']}: {row['description']}"
    )
    away_score, home_score = row["away_score"], row["home_score"]
    # A recorded 0-0 is ambiguous, so omit that score.
    if (
        isinstance(away_score, int)
        and isinstance(home_score, int)
        and (away_score != 0 or home_score != 0)
    ):
        statement += f" ({game.away_team_id} {away_score}, {game.home_team_id} {home_score})"
    return statement.rstrip(".") + "."


async def event_window(tools: AnalystTools) -> ToolResult | None:
    scope = tools.scope
    sources = requested_sources(tools.question)
    if sources and "possessions" not in sources:
        return None
    if (
        scope is None
        or scope.operation_reason
        or scope.operation is not None
        or scope.comparison is not None
    ):
        return None
    if scope.requires_clarification and not scope.game_ids:
        return None
    if scope.clarification_reason not in (None, "ambiguous_metric"):
        return None
    if scope.clarification_reason == "ambiguous_metric" and re.search(
        r"\b(?:runs?|stretch(?:es)?|deficits?|collapses?|collpase|droughts?)\b",
        tools.question,
        re.IGNORECASE,
    ):
        return None
    duration = _DURATION.search(tools.question)
    moment = moment_from_question(tools.question, scope.periods)
    half = re.search(r"\b(first|second) half\b", tools.question, re.I)
    regulation = re.search(r"\bregulation\b", tools.question, re.I)
    overtime = re.search(
        r"\b(?:overtime|(?:first|second|third)\s+overtime|[123](?:st|nd|rd)?\s*OT|"
        r"double\s+overtime|triple\s+overtime)\b",
        tools.question,
        re.I,
    )
    if re.search(r"\b(?:at|with)\s+\d{1,2}:\d{2}\b", tools.question) and moment is None:
        return ToolResult(
            status="ambiguous_entity",
            message="Which quarter or overtime does that clock refer to?",
            scope={"release": tools.release.version, **scope.model_dump(mode="json")},
        )
    whole_game = (
        duration is None
        and moment is None
        and not scope.periods
        and not regulation
        and not overtime
    )
    if whole_game and "possessions" not in sources:
        return None
    if not season_matches(tools):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message=f"Available season: {tools.release.season}.",
            scope={"release": tools.release.version, **scope.model_dump(mode="json")},
        )
    games = tools.selected_games(scope)
    if len(games) != 1:
        return ToolResult(
            status="ambiguous_entity" if games else "no_matching_results",
            message="Which archived game do you mean?"
            if games
            else "No archived game matches this event window; missing evidence is not absence.",
            choices=[f"{g.game_date}: {g.away_team_id} at {g.home_team_id}" for g in games[:8]],
            scope={"release": tools.release.version, **scope.model_dump(mode="json")},
        )
    game = games[0]
    try:
        events = list(
            (
                await tools.db.execute(
                    select(GameEvent)
                    .options(joinedload(GameEvent.player))
                    .join(Game, Game.id == GameEvent.game_id)
                    .where(Game.id == game.id, Game.release_id == tools.release.id)
                    .order_by(GameEvent.period, GameEvent.sequence, GameEvent.id)
                )
            ).scalars()
        )
    except Exception:
        return ToolResult(
            status="dependency_failure",
            message="Play-by-play for this event window is temporarily unavailable.",
            scope={"release": tools.release.version, **scope.model_dump(mode="json")},
        )
    if regulation:
        periods = [4] if duration else [1, 2, 3, 4]
    elif overtime:
        available = sorted({event.period for event in events if event.period >= 5})
        if re.search(
            r"\b(?:second|2(?:nd)?\s*OT|double)\s+overtime?\b|\b2(?:nd)?\s*OT\b",
            tools.question,
            re.I,
        ):
            periods = [6]
        elif re.search(
            r"\b(?:first|1(?:st)?\s*OT)\s+overtime?\b|\b1(?:st)?\s*OT\b",
            tools.question,
            re.I,
        ):
            periods = [5]
        elif duration:
            periods = [max(available, default=5)]
        else:
            periods = available or [5]
    elif duration and half:
        first = duration[1].casefold() in {"first", "opening"}
        start = 1 if half[1].casefold() == "first" else 3
        periods = [start if first else start + 1]
    elif scope.periods:
        periods = scope.periods
    elif whole_game:
        periods = sorted({event.period for event in events})
    else:
        first = duration is not None and duration[1].casefold() in {"first", "opening"}
        periods = [
            min((event.period for event in events), default=1)
            if first
            else max((event.period for event in events), default=4)
        ]
    bounds: dict[int, tuple[int, int]] = {}
    for period in periods:
        maximum = 720 if period <= 4 else 300
        low, high = 0, maximum
        if duration is not None:
            amount_text = duration[2]
            amount = (
                1
                if amount_text is None
                else int(amount_text)
                if amount_text.isdigit()
                else _NUMBERS[amount_text.casefold()]
            )
            seconds = amount * (60 if duration[3].casefold().startswith("min") else 1)
            if not 0 < seconds <= maximum:
                return ToolResult(
                    status="ambiguous_entity",
                    message="Choose an event interval within the named quarter or overtime.",
                    scope={"release": tools.release.version, **scope.model_dump(mode="json")},
                )
            if duration[1].lower() in {"first", "opening"}:
                low = maximum - seconds
            else:
                high = seconds
        elif moment is not None:
            low = high = moment.seconds_remaining
        bounds[period] = low, high
    rows = []
    source_receipts = []
    for event in events:
        seconds = _seconds(event)
        if seconds is None or event.period not in bounds:
            continue
        low, high = bounds[event.period]
        if not low <= seconds <= high:
            continue
        if scope.player_ids and event.player_id not in scope.player_ids:
            continue
        rows.append(
            {
                "event_id": event.id,
                "game_id": game.id,
                "sequence": event.sequence,
                "period": event.period,
                "clock": event.clock,
                "team_id": event.team_id,
                "player_id": event.player_id,
                "event_type": event.event_type,
                "description": event.description,
                "home_score": event.home_score,
                "away_score": event.away_score,
            }
        )
        reference = row_receipt(tools.release.version, "game_events", game.id, event.sequence)
        tools.provenance.capture_row(
            reference,
            collection="game_events",
            canonical_id=f"event:{game.nba_game_id}:{event.sequence}",
            row=event_projection(game, event),
            source_row_id=event.id,
            sequence_id=event.sequence,
        )
        statement = _event_statement(rows[-1], game)
        source_receipts.append(
            Evidence(
                evidence_id=reference,
                release_id=tools.release.version,
                game_id=game.id,
                text=statement,
                source_name=game.source_name,
                source_url=game.source_url,
                metadata={
                    "document_collection": "possessions",
                    "event_sequence": event.sequence,
                    "player_id": event.player_id,
                    "period": event.period,
                    "clock": event.clock,
                },
            )
        )
    window = {
        "periods": periods,
        "seconds_remaining": {
            str(period): {"min": low, "max": high} for period, (low, high) in bounds.items()
        },
        "selection": (
            "first"
            if duration and duration[1].casefold() in {"first", "opening"}
            else "last"
            if duration
            else "exact"
            if moment
            else "all"
        ),
    }
    if not rows:
        return ToolResult(
            status="no_matching_results",
            message="No play-by-play rows are available for that archived event window; "
            "this does not establish that nothing happened.",
            scope={
                "release": tools.release.version,
                **scope.model_dump(mode="json"),
                "event_window": window,
            },
        )
    statements = []
    for row in rows:
        statement = _event_statement(row, game)
        if sum(map(len, statements)) + len(statement) > 4500:
            statements.append("Further matching events are retained in the private record.")
            break
        statements.append(statement)
    text = " ".join(statements)
    digest = hashlib.sha256(
        json.dumps([tools.release.version, game.id, window, rows], sort_keys=True).encode()
    ).hexdigest()
    receipt = Evidence(
        evidence_id=f"{tools.release.version}:event-window:{digest}",
        release_id=tools.release.version,
        game_id=game.id,
        text=text,
        source_name=game.source_name,
        source_url=game.source_url,
        metadata={
            "document_collection": "possessions",
            "data_version": tools.release.version,
            "game_id": game.id,
            "event_window": window,
            "rows": rows,
            "source_evidence_ids": [item.evidence_id for item in source_receipts],
        },
    )
    claim = tools.claim(
        subject="team:NYK",
        metric="event_window",
        value={"rows": rows},
        unit="recorded events",
        games=[game],
        scope=scope,
        statement=text,
        denominator=None,
        evidence=[receipt],
        sample=len(rows),
        window=window,
        operation="event_window",
        considered_game_ids=[game.id],
        filters={"event_window": window},
        limitations=["Recorded events in this interval only; no causal inference."],
        population="recorded events in the selected game interval",
    )
    return ToolResult(
        status="ok",
        message="Scoped play-by-play receipts.",
        claims=[claim],
        evidence=[receipt, *source_receipts],
        scope={
            "release": tools.release.version,
            **scope.model_dump(mode="json"),
            "event_window": window,
        },
    )
