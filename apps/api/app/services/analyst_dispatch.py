"""Analyst dispatch. Pre-checks are driven by registry capability flags, never tool names."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_tool_registry import TOOLS_BY_NAME
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
        tools.db, call.question, intent=call.name, data_version=tools.release.version
    )
    if scope.requires_clarification:
        return ToolResult(
            status="ambiguous_entity",
            message="Ambiguous entity.",
            choices=scope.clarification_options,
        )
    for key in (
        "player_ids",
        "game_ids",
        "season_type",
        "opponent_id",
        "home_away",
        "game_result",
        "date_start",
        "date_end",
        "periods",
        "relative_game_count",
    ):
        authoritative = getattr(tools.scope, key)
        if authoritative:
            scope = scope.model_copy(update={key: authoritative})
    if scope.periods and not spec.supports_periods:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="These calculations support full-game box scores only.",
        )
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
    return await spec.resolve_handler()(tools, call, scope, games)
