"""Analyst calculations. Each claim names the operation and population it used.

Team aggregates live here; player aggregates, rankings and splits are cohesive
operation modules the dispatcher in `team` composes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.models.game import Game
from app.services.analyst_claim_support import team_claim
from app.services.analyst_rankings import (
    DEFENSIVE_EXTREME,
    MARGIN_EXTREMES,
    SCORING_EXTREMES,
    extremes,
    streaks,
    swings,
)
from app.services.analyst_team_splits import period_scoring, result_split, threshold_count
from app.services.evidence_contracts import ToolResult
from app.services.query_operations import STREAK_OPERATIONS
from app.services.query_resolution import ResolvedQuery

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

__all__ = ["team"]


_AGGREGATE_OPERATIONS = frozenset(
    {
        None,
        "team_record",
        "win_count",
        "loss_count",
        "game_count",
        "points_total",
        "points_average",
        "points_allowed",
        "average_margin",
    }
)


def _measure_values(
    operation: str | None,
    *,
    per_game: bool,
    wins: int,
    losses: int,
    game_total: int,
    points: int,
    allowed: int,
    margin_total: int,
    average_points: float,
    average_allowed: float,
    average_margin: float,
) -> list[tuple[str, float | int, str, float | int | None]]:
    """The claim values one operation contributes from the same final scores."""
    if operation == "team_record":
        return [("wins", wins, "wins", None), ("losses", losses, "losses", None)]
    if operation == "win_count":
        return [("wins", wins, "wins", None)]
    if operation == "loss_count":
        return [("losses", losses, "losses", None)]
    if operation == "game_count":
        return [("games", game_total, "games", None)]
    if operation == "points_total":
        # Only the requested total is emitted; points allowed answers another question.
        return (
            [("points_per_game", average_points, "points per game", points)]
            if per_game
            else [("points", points, "points", None)]
        )
    if operation == "points_allowed":
        return (
            [("points_allowed_per_game", average_allowed, "points per game", allowed)]
            if per_game
            else [("points_allowed", allowed, "points", None)]
        )
    if operation == "points_average":
        return [("points_per_game", average_points, "points per game", points)]
    if operation == "average_margin":
        return [("margin_per_game", average_margin, "points per game", margin_total)]
    if per_game:
        # No operation was requested; honour the aggregation the caller documented.
        return [
            ("wins", wins, "wins", None),
            ("losses", losses, "losses", None),
            ("points_per_game", average_points, "points per game", points),
            ("margin_per_game", average_margin, "points per game", margin_total),
        ]
    return [
        ("wins", wins, "wins", None),
        ("losses", losses, "losses", None),
        ("points", points, "points", None),
        ("margin", margin_total, "points", None),
    ]


def _aggregate(
    tools: AnalystTools,
    scope: ResolvedQuery,
    population: list[Game],
    aggregation: Literal["average", "total"],
) -> ToolResult:
    requested = scope.requested_measures
    operations: tuple[str | None, ...] = (
        tuple(measure.operation for measure in requested) if requested else (scope.operation,)
    )
    if any(operation not in _AGGREGATE_OPERATIONS for operation in operations):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="That operation is not computed from final scores.",
            scope=scope.model_dump(mode="json"),
        )
    games = population
    evidence = [tools.receipt(g) for g in games]
    wins = sum(tools.score(g)[0] > tools.score(g)[1] for g in games)
    losses = len(games) - wins
    points = sum(tools.score(g)[0] for g in games)
    allowed = sum(tools.score(g)[1] for g in games)
    margin_total = points - allowed
    average_points = round(points / len(games), 1)
    average_allowed = round(allowed / len(games), 1)
    average_margin = round(margin_total / len(games), 1)
    claims = []
    for index, operation in enumerate(operations):
        measure_aggregation = (
            requested[index].aggregation or aggregation if requested else aggregation
        )
        per_game = measure_aggregation == "average"
        for metric, value, unit, numerator in _measure_values(
            operation,
            per_game=per_game,
            wins=wins,
            losses=losses,
            game_total=len(games),
            points=points,
            allowed=allowed,
            margin_total=margin_total,
            average_points=average_points,
            average_allowed=average_allowed,
            average_margin=average_margin,
        ):
            claims.append(
                team_claim(
                    tools,
                    scope,
                    population=population,
                    metric=metric,
                    value=value,
                    unit=unit,
                    statement=(
                        f"Knicks {metric.replace('_', ' ')}: {value} over {len(games)} "
                        "archived games."
                    ),
                    games=games,
                    evidence=evidence,
                    numerator=numerator,
                    decimals=1 if metric.endswith("_per_game") else None,
                    operation=operation,
                )
            )
    return ToolResult(
        status="ok",
        message=(
            f"Computed from all {len(games)} games this scope admits; "
            "retrieval is not the denominator."
        ),
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


async def team(
    tools: AnalystTools,
    scope: ResolvedQuery,
    aggregation: Literal["average", "total"] = "total",
) -> ToolResult:
    """Answer the request's operation from the complete considered population."""
    operation = scope.operation
    if operation == "game_swings":
        return await swings(tools, scope)
    if operation == "period_scoring":
        return await period_scoring(tools, scope)
    if operation == "result_split":
        return await result_split(tools, scope)
    population = tools.considered_games(scope)
    if not population:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence that no such "
            "games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    if operation == "score_threshold":
        return threshold_count(tools, scope, population)
    if operation in STREAK_OPERATIONS:
        return streaks(tools, scope, population)
    if operation in SCORING_EXTREMES | MARGIN_EXTREMES | DEFENSIVE_EXTREME:
        return extremes(tools, scope, population)
    return _aggregate(tools, scope, population, aggregation)
