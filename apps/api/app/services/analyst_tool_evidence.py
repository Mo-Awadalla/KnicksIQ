"""get_evidence handler. Expands only references the backend already issued."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.evidence_contracts import ToolResult

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from app.services.query_resolution import ResolvedQuery


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    if not all(ref in tools.issued_evidence_ids for ref in call.evidence_ids):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="Only previously returned release references are allowed.",
        )
    return ToolResult(
        status="ok",
        message="Additional receipt detail.",
        evidence=[tools.evidence[ref] for ref in call.evidence_ids],
    )
