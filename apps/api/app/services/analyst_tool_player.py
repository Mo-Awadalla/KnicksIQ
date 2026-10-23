"""get_player_stats handler."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.analyst_calculations import player
from app.services.analyst_tool_narrative import _game_score
from app.services.evidence_contracts import PLAYER_METRICS, ToolResult
from app.services.player_threshold_games import threshold_call
from app.services.query_resolution import all_star_end

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from app.services.query_resolution import ResolvedQuery


def _all_star_comparison(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game], metric: str
) -> ToolResult:
    boundary = all_star_end(tools.release.season)
    if boundary is None:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="An independently supported All-Star boundary is required.",
        )
    populations = {
        "before": [g for g in games if g.game_date <= boundary],
        "after": [g for g in games if g.game_date > boundary],
    }
    results = {
        label: player(tools, scope, population, metric, "average")
        for label, population in populations.items()
    }
    claims, evidence = [], []
    for player_id in scope.player_ids:
        subject = f"player:{player_id}"
        baselines = {
            label: next((c for c in result.claims if c.subject_id == subject), None)
            for label, result in results.items()
        }
        before, after = baselines["before"], baselines["after"]
        if (
            before is None
            or after is None
            or not isinstance(before.value, (int, float))
            or not isinstance(after.value, (int, float))
        ):
            return ToolResult(
                status="incomplete_coverage",
                message="Both comparison populations require observed player appearances.",
            )
        sources = [
            e
            for result in results.values()
            for e in result.evidence
            if e.metadata.get("subject_id") == subject
        ]
        evidence.extend(sources)
        name = next((p.full_name for _, p in tools.rows if p.id == player_id), subject)
        window: dict[str, object] = {
            label: {
                "game_ids": claim.game_ids,
                "sample_size": claim.sample_size,
                "dates": claim.window,
            }
            for label, claim in (("before", before), ("after", after))
        }
        window.update(boundary=boundary.isoformat(), source_url="https://www.nba.com/allstar/2026")
        values = {"before": before.value, "after": after.value}
        values["delta"] = float(after.value) - float(before.value)
        claims.append(
            tools.claim(
                subject=subject,
                metric=f"{metric}:window_comparison",
                value=values,
                unit=f"{metric} per appearance",
                games=[
                    g
                    for g in games
                    if g.id in set((before.game_ids or []) + (after.game_ids or []))
                ],
                evidence=sources,
                statement=(
                    f"{name}: before the All-Star break, {float(before.value):.1f} {metric} "
                    f"per appearance over {before.sample_size} observed appearances; after, "
                    f"{float(after.value):.1f} over {after.sample_size}. Boundary: {boundary}; "
                    f"{scope.season_type or 'all-phase'} {tools.release.season} archive."
                ),
                scope=scope,
                sample=(before.sample_size or 0) + (after.sample_size or 0),
                denominator=None,
                baseline=[before.claim_id, after.claim_id],
                limitations=list(
                    dict.fromkeys(before.coverage_limitations + after.coverage_limitations)
                ),
                window=window,
            )
        )
    return ToolResult(
        status="incomplete_coverage"
        if any(result.status != "ok" for result in results.values())
        else "ok",
        message="Complete scoped before/after populations with observed appearance denominators.",
        claims=claims,
        evidence=evidence,
    )


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    metric = scope.metric or call.metric or "points"
    if call.metric is None and (
        len(scope.requested_metrics) > 1 or len(scope.requested_aggregations) > 1
    ):
        metrics = scope.requested_metrics or [scope.metric or "points"]
        aggregations = scope.requested_aggregations or ["average"]
        if not set(metrics) <= set(PLAYER_METRICS) or len(metrics) * len(aggregations) > 6:
            return ToolResult(
                status="unsupported_metric_or_scope",
                message="The requested compound statistics exceed the supported calculation.",
            )
        results = [
            player(tools, scope, games, requested_metric, aggregation)
            for requested_metric in metrics
            for aggregation in aggregations
        ]
        return ToolResult(
            status="ok"
            if all(result.status == "ok" for result in results)
            else "incomplete_coverage",
            message="Every requested player statistic over the resolved population.",
            claims=[claim for result in results for claim in result.claims],
            evidence=[item for result in results for item in result.evidence],
            scope=scope.model_dump(mode="json"),
        )
    if re.search(r"\bbefore\s+and\s+after\s+(?:the\s+)?all[ -]star\b", tools.question, re.I):
        return _all_star_comparison(tools, scope, games, metric)
    if tools.player_profile_requested():
        results = []
        for game in games:
            game_scope = scope.model_copy(
                update={"game_ids": [game.id], "relative_game_count": None}
            )
            results.extend(
                player(tools, game_scope, [game], key, "total")
                for key in ("points", "rebounds", "assists")
            )
            results.append(_game_score(tools, game_scope, game))
        return ToolResult(
            status="ok"
            if all(result.status == "ok" for result in results)
            else "incomplete_coverage",
            message="Complete requested player profile and archived game score.",
            claims=[claim for result in results for claim in result.claims],
            evidence=[item for result in results for item in result.evidence],
            scope=scope.model_dump(mode="json"),
        )
    if tools.season_window_comparison_requested():
        baseline_scope = tools.season_comparison_baseline_scope(scope)
        current = player(tools, scope, games, metric, "average")
        baseline = player(
            tools, baseline_scope, tools.selected_games(baseline_scope), metric, "average"
        )
        return ToolResult(
            status="ok" if current.status == baseline.status == "ok" else "incomplete_coverage",
            message="Requested appearance window and full scoped season baseline.",
            claims=current.claims + baseline.claims,
            evidence=current.evidence + baseline.evidence,
            scope=scope.model_dump(mode="json"),
        )
    return player(tools, scope, games, metric, scope.aggregation or call.aggregation)


async def find_player_games(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    """Native per-game threshold counts and matching games for the resolved player."""
    assert scope is not None
    return threshold_call(tools)
