"""Analyst dispatch. Pre-checks are driven by registry capability flags, never tool names."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_calculations import METRICS
from app.services.analyst_tool_registry import TOOLS_BY_NAME, period_tool_names
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import resolve_query

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall


async def execute_call(tools: AnalystTools, call: ToolCall) -> ToolResult:
    assert tools.scope is not None
    spec = TOOLS_BY_NAME[call.name]
    if not spec.needs_scope:
        return await spec.resolve_handler()(tools, call, None, [])
    if tools.scope.requires_clarification:
        return ToolResult(
            status="ambiguous_entity",
            message="Which subject did you mean?",
            choices=tools.scope.clarification_options,
        )
    if (
        tools.season != tools.release.season
        or re.search(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        and any(
            s != tools.release.season
            for s in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        )
    ):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message=f"Available season: {tools.release.season}.",
        )
    # Resolve model suggestions locally, but they may only narrow the user's scope.
    scope = await resolve_query(
        tools.db,
        call.question,
        intent=call.name,
        data_version=tools.release.version,
        default_season_type=tools.scope.season_type,
        default_all_phases=tools.scope.all_phases,
    )
    if scope.requires_clarification:
        return ToolResult(
            status="ambiguous_entity",
            message="Ambiguous entity.",
            choices=scope.clarification_options,
        )
    # The turn's resolved scope is authoritative: a call may add a subject the turn left
    # unnamed, but it may not change the phase, window, site or game reference the turn
    # resolved. Any-phase and all-phase turns are authoritative states too, so a call
    # phrase that defaults to the regular season cannot leak in.
    update: dict[str, object] = {
        "season_type": tools.scope.season_type,
        "all_phases": tools.scope.all_phases,
    }
    for key in (
        "player_ids",
        "game_ids",
        "opponent_id",
        "home_away",
        "game_result",
        "date_start",
        "date_end",
        "periods",
        "relative_game_count",
        "metric",
        "aggregation",
        "requested_metrics",
        "requested_aggregations",
    ):
        authoritative = getattr(tools.scope, key)
        if authoritative:
            update[key] = authoritative
    if spec.reads_metric and len(tools.scope.requested_metrics) > 1:
        selected_metric = call.metric or scope.metric
        if selected_metric not in tools.scope.requested_metrics:
            return ToolResult(
                status="unsupported_metric_or_scope",
                message="Choose one of the requested player metrics for this calculation.",
                scope=tools.scope.model_dump(mode="json"),
            )
        update["metric"] = selected_metric
    if len(tools.scope.requested_aggregations) > 1:
        update["aggregation"] = call.aggregation
    if tools.scope.relative_game_count:
        # Size and direction are one window; never take one from the model's rephrasing.
        update["relative_from_start"] = tools.scope.relative_from_start
    if not tools.scope.game_ids and scope.season_type != tools.scope.season_type:
        # The call's game ids were selected inside a phase the user did not ask for.
        update["game_ids"] = []
    scope = scope.model_copy(update=update)
    if spec.reads_metric and scope.metric is not None and scope.metric not in METRICS:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="The requested metric is not a player box-score calculation.",
            scope=scope.model_dump(mode="json"),
        )
    if scope.periods and not spec.supports_periods:
        capable = [name for name in period_tool_names() if name != call.name]
        message = "This calculation does not support period-level scope."
        if capable:
            message += " Period-capable tools: " + ", ".join(capable) + "."
        return ToolResult(status="unsupported_metric_or_scope", message=message)
    games = []
    if spec.needs_games:
        games = tools.selected_games(scope)
        if not games:
            return ToolResult(
                status="no_matching_results",
                message="No archived games match this scope; this is not evidence "
                "that no such games occurred.",
                scope=scope.model_dump(mode="json"),
            )
    if spec.needs_player and not scope.player_ids:
        return ToolResult(
            status="ambiguous_entity",
            message="Which Knicks player?",
            choices=sorted({p.full_name for _, p in tools.rows}),
        )
    result = await spec.resolve_handler()(tools, call, scope, games)
    if (
        spec.name == "discover_facts"
        and result.status == "no_matching_results"
        and (scope.opponent_id or _team_extreme(call.question))
    ):
        # Single-game highlights cannot answer a matchup or a team extreme; run the
        # population tool the discovery result points at instead of leaving the model to.
        follow = "get_player_stats" if scope.player_ids else "get_team_stats"
        return await TOOLS_BY_NAME[follow].resolve_handler()(tools, call, scope, games)
    return result


def _team_extreme(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:biggest|best|largest|worst|heaviest)\s+(?:win|victory|loss|defeat|blowout)\b"
            r"|\b(?:highest|most)[- ]scoring\b|\bmost points (?:in a game|scored)\b",
            question,
            re.I,
        )
    )
