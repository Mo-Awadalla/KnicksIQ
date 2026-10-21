"""compare_windows handler."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_calculations import player
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import resolve_query

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
    assert scope is not None
    if not call.baseline_question:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="Comparison requires an explicit baseline window.",
        )
    requested_seasons = re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", call.baseline_question)
    if any(season != tools.release.season for season in requested_seasons):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="The baseline season is unavailable in this release.",
        )
    baseline_scope = await resolve_query(
        tools.db, call.baseline_question, intent=call.name, data_version=tools.release.version
    )
    # A baseline may intentionally use a different phase/window, never another release.
    baseline_scope = baseline_scope.model_copy(update={"player_ids": scope.player_ids})
    baseline_games = tools.selected_games(baseline_scope)
    metric = call.metric or scope.metric or "points"
    first = player(tools, scope, games, metric, call.aggregation)
    second = player(tools, baseline_scope, baseline_games, metric, call.aggregation)
    if not first.claims or not second.claims:
        return ToolResult(
            status="incomplete_coverage",
            message="One comparison population is unavailable.",
            claims=first.claims + second.claims,
            evidence=first.evidence + second.evidence,
        )
    comparisons = []
    for a in first.claims:
        b = next((b for b in second.claims if b.subject_id == a.subject_id), None)
        if (
            b is None
            or not isinstance(a.value, (int, float))
            or not isinstance(b.value, (int, float))
        ):
            continue
        comparisons.append(
            tools.claim(
                subject=a.subject_id or "",
                metric=f"{metric}:delta",
                value=float(a.value) - float(b.value),
                unit=a.unit or "",
                games=list({g.id: g for g in games + baseline_games}.values()),
                evidence=first.evidence + second.evidence,
                statement=(f"{a.statement} Baseline: {b.statement}"),
                scope=scope,
                sample=a.sample_size or 0,
                denominator=a.denominator,
                baseline=[a.claim_id, b.claim_id],
                window={"current": a.game_ids, "baseline": b.game_ids},
            )
        )
    return ToolResult(
        status="ok",
        message="Both complete applicable archive populations.",
        claims=first.claims + second.claims + comparisons,
        evidence=first.evidence + second.evidence,
    )
