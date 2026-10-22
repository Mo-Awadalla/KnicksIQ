"""get_player_stats handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.analyst_calculations import player

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall, ToolResult
    from app.services.query_resolution import ResolvedQuery


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    metric = scope.metric or call.metric or "points"
    return player(tools, scope, games, metric, scope.aggregation or call.aggregation)
