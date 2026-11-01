"""Player aggregates, derived ratios and leaderboards."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import ResolvedQuery
from basketball_core.analytics.calculations import aggregate_rows, count_double_doubles
from basketball_core.analytics.registry import STAT_REGISTRY

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

METRICS = (
    "points",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "three_pointers_made",
    "plus_minus",
    "minutes",
)

# Percentage stats read made and attempted columns together, so a "three-point
# percentage" is never delivered as a total of made threes.
_METRIC_IDS = {
    "three_point_percentage": "three_pointers_made:percentage",
    "free_throw_percentage": "free_throws_made:percentage",
    "field_goal_percentage": "field_goal_percentage",
    "true_shooting_percentage": "true_shooting_percentage",
    "effective_field_goal_percentage": "effective_field_goal_percentage",
    "assist_turnover_ratio": "assist_turnover_ratio",
    "double_doubles": "double_doubles",
    "triple_doubles": "triple_doubles",
    "starts": "starts",
}
_APPEARANCE_LIMITATION = "Only observed appearances in the available archive."


def metric_id_for(stat: str) -> str:
    """The claim metric id for one canonical player stat."""
    return _METRIC_IDS.get(stat, stat)


def _window_games(tools: AnalystTools, games: list[Game], scope: ResolvedQuery) -> list[Game]:
    if scope.relative_game_count and "appearance" not in tools.question.lower():
        count = scope.relative_game_count
        return games[:count] if scope.relative_game_position == "first" else games[-count:]
    return games


def observed_appearances(
    tools: AnalystTools, player_id: int, game_map: dict[int, Game]
) -> tuple[list[tuple[PlayerGameStat, Player]], list[int], int]:
    """Observed rows for one player, the archived games with no row, and DNP rows."""
    rows = [(s, p) for s, p in tools.rows if s.player_id == player_id and s.game_id in game_map]
    absent = sorted(set(game_map) - {s.game_id for s, _ in rows})
    observed = [(s, p) for s, p in rows if s.minutes > 0]
    return observed, absent, len(rows) - len(observed)


def _derived_value(
    stat: str, observed: list[tuple[PlayerGameStat, Player]]
) -> tuple[float | None, str, str]:
    """Return the aggregate value, unit and metric id for one derived player stat.

    A percentage or ratio with a zero denominator stays undefined (`None`) instead of
    being reported as a measured zero.
    """
    stats = [s for s, _ in observed]
    if stat == "starts":
        return float(sum(bool(s.starter) for s in stats)), "starts", metric_id_for("starts")
    if stat in {"double_doubles", "triple_doubles"}:
        index = 0 if stat == "double_doubles" else 1
        value = sum(count_double_doubles(s)[index] for s in stats)
        return float(value), "count", metric_id_for(stat)
    value = aggregate_rows(stats, [stat])[stat]
    if value is None:
        return None, "", metric_id_for(stat)
    kind = STAT_REGISTRY[stat].kind
    unit = (
        "percent"
        if kind == "percentage"
        else "ratio"
        if kind == "ratio"
        else stat.replace("_", " ")
    )
    return float(value), unit, metric_id_for(stat)


def _derived_player_claims(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game], stat: str
) -> ToolResult:
    game_map = {g.id: g for g in games}
    claims, evidence = [], []
    missing = False
    undefined: list[str] = []
    for player_id in scope.player_ids:
        observed, absent, dropped = observed_appearances(tools, player_id, game_map)
        if not observed:
            continue
        value, unit, metric = _derived_value(stat, observed)
        count = len(observed)
        receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in observed]
        evidence.extend(receipts)
        limitations = [_APPEARANCE_LIMITATION]
        if dropped:
            limitations.append(
                f"{dropped} archived game(s) recorded zero minutes and are not counted as "
                "appearances."
            )
        if absent:
            missing = True
            limitations.append(f"Missing player rows for archived game IDs: {absent}.")
        name = observed[0][1].full_name
        label = STAT_REGISTRY[stat].label
        if value is None:
            denominator = (
                "attempt count" if STAT_REGISTRY[stat].kind == "percentage" else ("denominator")
            )
            undefined.append(
                f"{name}'s {label.lower()} is undefined across {count} observed appearances: "
                f"the {denominator} is zero, so no ratio is reported."
            )
            continue
        if stat == "starts":
            statement = (
                f"{name} started {int(value)} of {count} observed appearances in the "
                f"{tools.release.season} archive."
            )
        elif stat in {"double_doubles", "triple_doubles"}:
            statement = (
                f"{name} recorded {int(value)} {label.lower()} across {count} observed "
                f"appearances in the {tools.release.season} archive."
            )
        else:
            decimals = 2 if unit == "ratio" else 1
            statement = (
                f"{name}: {label.lower()} of {value:.{decimals}f} across {count} observed "
                f"appearances in the {tools.release.season} archive."
            )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=metric,
                value=(
                    value
                    if stat not in {"double_doubles", "triple_doubles", "starts"}
                    else int(value)
                ),
                unit=unit,
                games=[game_map[s.game_id] for s, _ in observed],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=count,
                denominator=count,
                limitations=limitations,
                window={
                    "date_start": str(games[0].game_date),
                    "date_end": str(games[-1].game_date),
                }
                if games
                else None,
            )
        )
    coverage = " ".join(undefined)
    if claims and coverage:
        message = (
            "Calculated from all applicable database rows; retrieval is not the denominator. "
            + coverage
        )
    elif coverage:
        message = coverage
    elif claims:
        message = "Calculated from all applicable database rows; retrieval is not the denominator."
    else:
        message = "No observed appearances."
    return ToolResult(
        status=(
            "incomplete_coverage"
            if missing or undefined
            else "ok"
            if claims
            else "no_matching_results"
        ),
        message=message,
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


def player(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game], metric: str, aggregation: str
) -> ToolResult:
    """Answer a player question from every observed appearance the scope admits."""
    games = _window_games(tools, games, scope)
    if scope.stat:
        return _derived_player_claims(tools, scope, games, scope.stat)
    game_map = {g.id: g for g in games}
    claims, evidence = [], []
    missing = False
    for player_id in scope.player_ids:
        all_rows = [
            (s, p) for s, p in tools.rows if s.player_id == player_id and s.game_id in game_map
        ]
        # Zero minutes means observed DNP, not an appearance; missing rows remain unknown.
        absent = sorted(set(game_map) - {s.game_id for s, _ in all_rows})
        rows = [(s, p) for s, p in all_rows if s.minutes > 0]
        if scope.relative_game_count:
            count = scope.relative_game_count
            rows = rows[:count] if scope.relative_game_position == "first" else rows[-count:]
        if not rows:
            continue
        count = len(rows)
        total = sum(getattr(s, metric) for s, _ in rows)
        value = total / count if aggregation == "average" else total
        receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in rows]
        evidence.extend(receipts)
        limitations = [_APPEARANCE_LIMITATION]
        if absent:
            missing = True
            limitations.append(f"Missing player rows for archived game IDs: {absent}.")
        name = rows[0][1].full_name
        unit = f"{metric} per appearance" if aggregation == "average" else metric
        statement = (
            f"{name}: {value:.1f} {unit} across {count} observed appearances "
            f"in the {tools.release.season} {scope.season_type or 'all-phase'} archive."
        )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=f"{metric}:{aggregation}",
                value=value,
                unit=unit,
                games=[game_map[s.game_id] for s, _ in rows],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=count,
                denominator=count if aggregation == "average" else None,
                numerator=total if aggregation == "average" else None,
                limitations=limitations,
                window={
                    "date_start": str(games[0].game_date),
                    "date_end": str(games[-1].game_date),
                }
                if games
                else None,
            )
        )
    return ToolResult(
        status=("incomplete_coverage" if missing else "ok") if claims else "no_matching_results",
        message="Calculated from all applicable database rows; retrieval is not the denominator."
        if claims
        else "No observed appearances.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


def player_threshold(tools: AnalystTools, scope: ResolvedQuery) -> ToolResult:
    """Count a named player's qualifying appearances against one numeric cutoff.

    The subject is the player's own box-score row, never the team's final score.
    """
    spec = scope.threshold
    if spec is None:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="That count needs a numeric cutoff.",
            scope=scope.model_dump(mode="json"),
        )
    metric = scope.stat or scope.metric or "points"
    games = tools.considered_games(scope)
    if not games:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence that no such "
            "games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    game_map = {g.id: g for g in games}
    claims, evidence = [], []
    missing = False
    for player_id in scope.player_ids:
        observed, absent, dropped = observed_appearances(tools, player_id, game_map)
        if not observed:
            continue
        qualifying = [row for row in observed if spec.accepts(getattr(row[0], metric))]
        count = len(observed)
        receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in observed]
        evidence.extend(receipts)
        limitations = [_APPEARANCE_LIMITATION]
        if dropped:
            limitations.append(
                f"{dropped} archived game(s) recorded zero minutes and are not counted as "
                "appearances."
            )
        if absent:
            missing = True
            limitations.append(f"Missing player rows for archived game IDs: {absent}.")
        name = observed[0][1].full_name
        statement = (
            f"{name} met the cutoff of {spec.describe(unit=metric.replace('_', ' '))} "
            f"in {len(qualifying)} of {count} observed appearances "
            f"in the {tools.release.season} archive."
        )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=f"{metric}:threshold",
                value=len(qualifying),
                unit="games",
                games=[game_map[s.game_id] for s, _ in observed],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=len(qualifying),
                denominator=count,
                eligibility={
                    "subject": spec.subject,
                    "comparator": spec.comparator,
                    "threshold": spec.value,
                    "metric": metric,
                    "qualifying_game_ids": [s.game_id for s, _ in qualifying],
                },
                operation="player_threshold",
                considered_game_ids=[g.id for g in games],
                limitations=limitations,
            )
        )
    return ToolResult(
        status=("incomplete_coverage" if missing else "ok") if claims else "no_matching_results",
        message=(
            "Counted qualifying player appearances over the complete considered games; "
            "retrieval is not the denominator."
        )
        if claims
        else "No observed player appearances.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


def leaderboard(
    tools: AnalystTools, scope: ResolvedQuery, aggregation: Literal["average", "total"] = "total"
) -> ToolResult:
    """Rank Knicks players by one metric over every game the scope admits.

    The ranking population is the complete considered scope, so an early descriptive game
    reference never shrinks it, zero-minute rows are not appearances, and every tied leader
    is reported instead of only the first name.
    """
    metric = scope.metric or "points"
    games = tools.considered_games(scope)
    if not games:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence that no such "
            "games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    game_map = {g.id: g for g in games}
    grouped: dict[int, list[tuple[PlayerGameStat, Player]]] = {}
    for stat, player in tools.rows:
        if stat.game_id in game_map and stat.team_id == "NYK" and stat.minutes > 0:
            grouped.setdefault(stat.player_id, []).append((stat, player))
    if not grouped:
        return ToolResult(
            status="no_matching_results",
            message="No observed player box-score rows match this scope.",
            evidence=[tools.receipt(game) for game in games],
            scope=scope.model_dump(mode="json"),
        )
    per_game = aggregation == "average" or bool(
        re.search(r"\b(?:per game|average|avg|mean)\b", tools.question, re.I)
    )
    ranked: list[tuple[float, int, str, list[tuple[PlayerGameStat, Player]]]] = []
    for player_id, rows in grouped.items():
        total = sum(getattr(stat, metric) for stat, _ in rows)
        value = total / len(rows) if per_game else total
        ranked.append((float(value), player_id, rows[0][1].full_name, rows))
    ranked.sort(key=lambda item: (-item[0], item[3][0][1].full_name, item[1]))
    best = ranked[0][0]
    leaders = [item for item in ranked if abs(item[0] - best) < 1e-9]
    claims, evidence = [], []
    for value, player_id, name, rows in leaders:
        receipts = [tools.receipt(game_map[stat.game_id], stat, player) for stat, player in rows]
        evidence.extend(receipts)
        key = "average" if per_game else "total"
        displayed = round(value, 1) if per_game else int(value)
        if len(leaders) > 1:
            subject_phrase = f"{name} tied for the Knicks lead"
        else:
            subject_phrase = f"{name} led the Knicks"
        statement = (
            f"{subject_phrase} in {metric} with {displayed} {key} across {len(rows)} observed "
            f"appearances in {len(game_map)} considered {tools.release.season} games."
        )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=f"{metric}:leader",
                value={"name": name, key: displayed},
                unit=metric,
                games=[game_map[stat.game_id] for stat, _ in rows],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=len(rows),
                denominator=len(rows),
                limitations=[
                    _APPEARANCE_LIMITATION,
                    f"Ranked over {len(grouped)} Knicks players with observed appearances in "
                    f"the {len(game_map)} considered games.",
                ],
                operation="player_leaderboard",
                considered_game_ids=[g.id for g in games],
            )
        )
    return ToolResult(
        status="ok",
        message=(
            f"Ranked {len(grouped)} Knicks players over {len(game_map)} considered games; "
            "retrieval is not the denominator."
        ),
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
