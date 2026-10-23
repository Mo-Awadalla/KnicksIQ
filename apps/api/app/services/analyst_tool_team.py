"""get_team_stats handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.box_score import TeamGameStat
from app.services.analyst_calculations import METRICS, team
from app.services.analyst_tool_narrative import _game_score
from app.services.evidence_contracts import ToolResult
from app.services.population_facts import (
    ScoreThresholdCount,
    is_player_leader_request,
    player_leader_fact,
    score_threshold_count,
)
from app.services.query_text import is_game_score_request
from sqlalchemy import select

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
    if is_game_score_request(tools.question):
        if len(games) != 1:
            return ToolResult(
                status="ambiguous_entity",
                message="Which game score?",
                choices=[str(game.game_date) for game in games],
            )
        return _game_score(tools, scope, games[0])
    if is_player_leader_request(tools.question):
        return _team_leaders(tools, scope, games)
    threshold_count = score_threshold_count(tools.question, games)
    if threshold_count is not None:
        return _threshold_count(tools, scope, games, threshold_count)
    groups = tools.requested_team_groups()
    if groups:
        return await _team_comparison(tools, scope, groups)
    return team(tools, scope, games, scope.aggregation or call.aggregation)


def _team_leaders(
    tools: AnalystTools,
    scope: ResolvedQuery,
    games: list[Game],
) -> ToolResult:
    metric = scope.metric
    if metric is None or metric not in METRICS:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="Specify a supported leader statistic.",
        )
    fact = player_leader_fact(
        tools.rows,
        games,
        metric,
        tools.question,
        supported_metrics=METRICS,
    )
    if fact is None:
        return ToolResult(
            status="incomplete_coverage",
            message="Complete scoped player box scores are unavailable.",
        )

    game_map = {game.id: game for game in games}
    evidence = [
        tools.receipt(game_map[stat.game_id], stat, player) for stat, player in fact.evidence_rows
    ]
    if fact.single_game_high:
        rows = [
            {
                "player": entry.player.full_name,
                "date": entry.game.game_date.isoformat(),
                "opponent": (
                    entry.game.away_team_id
                    if entry.game.home_team_id == "NYK"
                    else entry.game.home_team_id
                ),
                "value": entry.value,
            }
            for entry in fact.tied_rows
        ]
        value = {"maximum": fact.value, "rows": rows}
        metric_id = f"{metric}:single_game_high"
        statement = (
            f"Knicks' single-game high was {fact.value:g} {fact.label}, recorded by "
            + "; ".join(
                f"{row['player']} ({row['value']:g} on {row['date']} vs {row['opponent']})"
                for row in rows
            )
            + "."
        )
        unit = fact.label
        eligibility = {
            "player": "NYK box-score appearances with minutes > 0",
            "reduction": "maximum per-game stat row",
            "ties": "all tied rows",
        }
    else:
        value = {"leaders": list(fact.leaders), "total": fact.value}
        metric_id = f"{metric}:leaders"
        statement = (
            f"{', '.join(fact.leaders)} led the Knicks with {fact.value:g} total "
            f"{fact.label} across {len(games)} archived games."
        )
        unit = f"total {fact.label}"
        eligibility = {
            "player": "NYK box-score rows",
            "reduction": "season total by player",
            "ties": "all leaders",
        }

    claim = tools.claim(
        subject="team:NYK",
        metric=metric_id,
        value=value,
        unit=unit,
        games=games,
        evidence=evidence,
        scope=scope,
        sample=fact.sample_size,
        denominator=None,
        eligibility=eligibility,
        statement=statement,
    )
    return ToolResult(
        status="ok",
        message="Complete scoped player leader population.",
        claims=[claim],
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


def _threshold_count(
    tools: AnalystTools,
    scope: ResolvedQuery,
    games: list[Game],
    threshold_count: ScoreThresholdCount,
) -> ToolResult:
    evidence = [tools.receipt(g) for g in games]
    eligibility: dict[str, Any] = {"game": "archived Knicks game"}
    eligibility["score_predicate"] = threshold_count.predicate
    eligibility["matching_game_ids"] = list(threshold_count.matching_game_ids)
    threshold_description = (
        f" with {'opponent' if threshold_count.opponent_score else 'NYK'} points "
        f"{threshold_count.threshold.symbol} {threshold_count.threshold.value:g}"
    )
    metric = "games:count"
    value = threshold_count.value
    claim = tools.claim(
        subject="team:NYK",
        metric=metric,
        value=value,
        unit=metric,
        games=games,
        evidence=evidence,
        scope=scope,
        sample=len(games),
        denominator=None,
        eligibility=eligibility,
        statement=(
            f"Knicks {metric}{threshold_description}: {value} "
            f"over {len(games)} archived games "
            f"in {tools.scope_label(scope, games)}."
        ),
    )
    return ToolResult(
        status="ok",
        message="Archive team totals.",
        claims=[claim],
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


async def _team_comparison(
    tools: AnalystTools,
    scope: ResolvedQuery,
    groups: list[tuple[str, list[Game]]],
) -> ToolResult:
    """Use the existing team-scope definitions and box-score denominators."""
    metrics = tools.team_comparison_metrics(scope)
    game_map = {g.id: g for _, games in groups for g in games}
    team_rows: dict[int, TeamGameStat] = {}
    if metrics in {("turnovers_per_game",), ("field_goal_percentage",)}:
        team_rows = {
            r.game_id: r
            for r in (
                await tools.db.execute(
                    select(TeamGameStat).where(
                        TeamGameStat.release_id == tools.release.id,
                        TeamGameStat.game_id.in_(game_map),
                        TeamGameStat.team_id == "NYK",
                    )
                )
            ).scalars()
        }
        if set(team_rows) != set(game_map):
            return ToolResult(
                status="incomplete_coverage",
                message="Complete scoped team box scores are unavailable.",
            )
    claims, evidence = [], []
    for label, games in groups:
        if not games:
            return ToolResult(
                status="incomplete_coverage", message=f"{label}: no matching archived games."
            )
        ids = {g.id for g in games}
        receipts = [tools.receipt(g) for g in games]
        values: dict[str, int | float]
        if metrics == ("bench_points_per_team_game",):
            rows = [(s, p) for s, p in tools.rows if s.game_id in ids]
            if {s.game_id for s, _ in rows} != ids:
                return ToolResult(
                    status="incomplete_coverage",
                    message=f"{label}: complete player box scores are unavailable.",
                )
            values = {
                "bench_points_per_team_game": sum(s.points for s, _ in rows if not s.starter)
                / len(games)
            }
            receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in rows]
        elif metrics == ("turnovers_per_game",):
            values = {"turnovers_per_game": sum(team_rows[i].turnovers for i in ids) / len(games)}
            receipts = [tools.receipt(game_map[i], team_rows[i]) for i in ids]
        elif metrics == ("field_goal_percentage",):
            attempts = sum(team_rows[i].field_goals_attempted for i in ids)
            if not attempts:
                return ToolResult(
                    status="incomplete_coverage", message=f"{label}: no field-goal attempts."
                )
            values = {
                "field_goal_percentage": 100
                * sum(team_rows[i].field_goals_made for i in ids)
                / attempts
            }
            receipts = [tools.receipt(game_map[i], team_rows[i]) for i in ids]
        elif metrics == ("points_allowed_per_game",):
            values = {"points_allowed_per_game": sum(tools.score(g)[1] for g in games) / len(games)}
        elif metrics == ("points_per_game",):
            values = {"points_per_game": sum(tools.score(g)[0] for g in games) / len(games)}
        else:
            wins = sum(tools.score(g)[0] > tools.score(g)[1] for g in games)
            values = {"games": len(games), "wins": wins, "losses": len(games) - wins}
            if "average_margin" in metrics:
                values["average_margin"] = sum(
                    tools.score(g)[0] - tools.score(g)[1] for g in games
                ) / len(games)
        evidence.extend(receipts)
        description = ", ".join(
            f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}"
            for key, value in values.items()
        )
        claims.append(
            tools.claim(
                subject="team:NYK",
                metric="team_comparison",
                value=values,
                unit="requested team comparison metrics",
                games=games,
                evidence=receipts,
                scope=scope,
                sample=len(games),
                denominator=len(games),
                window={
                    "comparison_group": label,
                    "date_start": str(games[0].game_date),
                    "date_end": str(games[-1].game_date),
                },
                eligibility={"game": "complete requested comparison group"},
                statement=f"{label}: {description} across {len(games)} archived games.",
            )
        )
    return ToolResult(
        status="ok",
        message="All requested team comparison populations.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
