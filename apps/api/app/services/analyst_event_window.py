"""Deterministic, release-bound receipts for a pinned game's event interval."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.analyst_dispatch import season_matches
from app.services.analyst_provenance import event_projection, row_receipt
from app.services.analyst_render import deterministic_text
from app.services.archive_clock import GameMoment, moment_from_question
from app.services.evidence_contracts import ClaimUse, Evidence, ProposedAnswer, ToolResult
from app.services.query_classifier import classify_query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

if TYPE_CHECKING:
    from app.services.analyst_loop import AnalystLoop
    from app.services.analyst_tools import AnalystTools

_DURATION = re.compile(
    r"\b(first|opening|last|final|closing)\s+"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
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


async def event_window(tools: AnalystTools) -> ToolResult | None:
    """Describe actual matching rows, never a full-game total or an inferred cause."""
    scope = tools.scope
    if scope is None or scope.operation_reason or classify_query(tools.question).is_aggregative:
        return None
    if scope.requires_clarification and (scope.player_ids or not scope.game_ids):
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
    if re.search(r"\b(?:at|with)\s+\d{1,2}:\d{2}\b", tools.question) and moment is None:
        return ToolResult(
            status="ambiguous_entity",
            message="Which quarter or overtime does that clock refer to?",
            scope=scope.model_dump(mode="json"),
        )
    if duration is None and moment is None and not scope.periods:
        return None
    if not season_matches(tools):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message=f"Available season: {tools.release.season}.",
            scope=scope.model_dump(mode="json"),
        )
    games = tools.selected_games(scope)
    if len(games) != 1:
        return ToolResult(
            status="ambiguous_entity" if games else "no_matching_results",
            message="Which archived game do you mean?"
            if games
            else "No archived game matches this event window; missing evidence is not absence.",
            choices=[f"{g.game_date}: {g.away_team_id} at {g.home_team_id}" for g in games[:8]],
            scope=scope.model_dump(mode="json"),
        )
    game = games[0]
    # Recheck the release on the row query, not merely in the previously loaded game list.
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
            scope=scope.model_dump(mode="json"),
        )
    periods = scope.periods or [
        min((e.period for e in events), default=1)
        if duration and duration[1].lower() in {"first", "opening"}
        else max((e.period for e in events), default=4)
    ]
    bounds: dict[int, tuple[int, int]] = {}
    for period in periods:
        maximum = 720 if period <= 4 else 300
        low, high = 0, maximum
        if duration is not None:
            text = duration[2].lower()
            amount = int(text) if text.isdigit() else _NUMBERS[text]
            seconds = amount * (60 if duration[3].lower().startswith("min") else 1)
            if not 0 < seconds <= maximum:
                return ToolResult(
                    status="ambiguous_entity",
                    message="Choose an event interval within the named quarter or overtime.",
                    scope=scope.model_dump(mode="json"),
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
        source_receipts.append(
            Evidence(
                evidence_id=reference,
                release_id=tools.release.version,
                game_id=game.id,
                text=event.description,
                source_name=game.source_name,
                source_url=game.source_url,
            )
        )
    if not rows:
        return ToolResult(
            status="no_matching_results",
            message="No play-by-play rows are available for that archived event window; "
            "this does not establish that nothing happened.",
            scope=scope.model_dump(mode="json"),
        )
    window = {
        "periods": periods,
        "seconds_remaining": {
            str(period): {"min": low, "max": high} for period, (low, high) in bounds.items()
        },
    }
    header = (
        f"{game.game_date}: {game.away_team_id} at {game.home_team_id}. Archived event receipts:"
    )
    statements = [header]
    for row in rows:
        statement = (
            f"Q{row['period']} {row['clock']}: {row['description']} "
            f"({game.away_team_id} {row['away_score']}, {game.home_team_id} {row['home_score']})."
        )
        if sum(map(len, statements)) + len(statement) > 4500:
            statements.append("Further matching events are included in the cited receipt.")
            break
        statements.append(statement)
    statements.append("These receipts describe recorded events, not their causes.")
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
        scope=scope.model_dump(mode="json"),
    )


async def window_response(loop: AnalystLoop, reason: str, degraded: bool) -> dict[str, Any] | None:
    window = await event_window(loop.tools)
    if window is None:
        return None
    loop.results.append(window)
    for item in window.evidence:
        loop.tools.evidence[item.evidence_id] = item
        loop.tools.issued_evidence_ids.add(item.evidence_id)
    if not window.claims:
        text = window.message
        if window.choices:
            text += " " + "; ".join(window.choices)
        degraded = degraded or window.status == "dependency_failure"
        return loop.render(
            ProposedAnswer(text=text),
            llm=False,
            warning=(reason or window.message) if degraded else "",
            degraded=degraded,
            delivered=[],
        )
    answer = ProposedAnswer(
        text=deterministic_text(window.claims),
        claims=[
            ClaimUse(claim_id=claim.claim_id, displayed_value=claim.value)
            for claim in window.claims[:30]
        ],
    )
    return loop.render(answer, llm=False, degraded=degraded, delivered=window.claims)
