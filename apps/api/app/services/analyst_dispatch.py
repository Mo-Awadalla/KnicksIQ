"""Analyst dispatch."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.evidence_contracts import ToolCall, ToolResult
from app.services.query_resolution import resolve_query

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools
from app.services.analyst_calculations import player, team
from app.services.analyst_discovery import discover


async def execute_call(tools: AnalystTools, call: ToolCall) -> ToolResult:
    assert tools.scope is not None
    if call.name == "get_evidence":
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
    if scope.periods and call.name != "search_archive":
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="These calculations support full-game box scores only.",
        )
    games = tools.selected_games(scope)
    if not games:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence "
            "that no such games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    if call.name == "search_archive":
        return await tools.search(call, scope, games)
    if call.name == "get_team_stats":
        return team(tools, scope, games, call.aggregation)
    if call.name == "discover_facts":
        return discover(tools, scope, games)
    if not scope.player_ids:
        return ToolResult(
            status="ambiguous_entity",
            message="Which Knicks player?",
            choices=sorted({p.full_name for _, p in tools.rows}),
        )
    metric = call.metric or scope.metric or "points"
    if call.name == "compare_windows":
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
    return player(tools, scope, games, metric, call.aggregation)
