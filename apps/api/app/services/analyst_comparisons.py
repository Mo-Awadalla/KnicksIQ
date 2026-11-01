"""Grouped comparison claims retain each group's population and denominator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.services.analyst_claim_support import team_claim
from app.services.analyst_player_stats import metric_id_for
from app.services.evidence_contracts import ToolResult, VerifiedClaim
from app.services.query_comparison_specs import (
    ComparisonGroup,
    ComparisonSpec,
    team_claim_metrics,
)
from app.services.query_comparison_windows import window_rows
from app.services.query_comparisons import comparison_pool
from app.services.query_resolution import ResolvedQuery
from basketball_core.analytics.calculations import aggregate_rows
from basketball_core.analytics.registry import STAT_REGISTRY

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

_COMPARISON_LIMITATION = (
    "Each group is calculated over the games it selected; the groups are never added "
    "together and retrieval is not a denominator."
)


def _group_eligibility(
    scope: ResolvedQuery, group: ComparisonGroup, games: list[Game]
) -> dict[str, Any]:
    """The typed population of one group, including the game count a fact may ask for."""
    spec = scope.comparison
    assert spec is not None
    return {
        "operation": "team_comparison",
        "comparison_group": group.key,
        "comparison_kind": group.kind,
        "measure": spec.measure,
        "coverage": spec.coverage,
        "considered_games": len(games),
    }


def _group_filters(scope: ResolvedQuery, group: ComparisonGroup) -> dict[str, Any]:
    spec = scope.comparison
    assert spec is not None
    shared = spec.filters.model_dump(
        include={"opponent_id", "home_away", "game_result"}, exclude_none=True
    )
    return (
        shared
        | group.model_dump(include={"opponent_id", "home_away", "conference"}, exclude_none=True)
        | {"comparison_group": group.key}
    )


def _group_window(
    scope: ResolvedQuery, group: ComparisonGroup, games: list[Game]
) -> dict[str, Any]:
    spec = scope.comparison
    assert spec is not None and games
    window: dict[str, Any] = {
        "date_start": str(min(game.game_date for game in games)),
        "date_end": str(max(game.game_date for game in games)),
    }
    selected = group.window or spec.filters.window
    if selected is not None:
        window.update({f"{selected.position}_n": selected.count, "basis": spec.basis})
    if group.phase is not None:
        window["all_star_break"] = "before" if group.phase == "before_all_star" else "after"
    return window


_COMPONENT_LABELS = {
    "points": "points",
    "points_allowed": "points allowed",
    "margin": "margin",
}


def _team_claims(
    tools: AnalystTools, scope: ResolvedQuery, group: ComparisonGroup, games: list[Game]
) -> list[VerifiedClaim]:
    """One scalar claim per requested team metric, over this group's own games."""
    spec = scope.comparison
    assert spec is not None
    pairs = [tools.score(game) for game in games]
    count = len(pairs)
    wins = sum(own > other for own, other in pairs)
    totals = {
        "points": sum(own for own, _ in pairs),
        "points_allowed": sum(other for _, other in pairs),
    }
    totals["margin"] = totals["points"] - totals["points_allowed"]
    eligibility = _group_eligibility(scope, group, games)
    evidence = [tools.receipt(game) for game in games]
    limitations = [_COMPARISON_LIMITATION]
    if spec.team_metric == "record_and_margin":
        limitations.append(
            "The record and the average margin are separate measures; neither one alone "
            "establishes which group was better."
        )
    claims: list[VerifiedClaim] = []
    for metric in team_claim_metrics(spec):
        if metric in {"wins", "losses"}:
            won = metric == "wins"
            value: float | int = wins if won else count - wins
            unit, numerator, decimals = metric, None, 0
            statement = (
                f"{group.label}: {value} {'win' if won else 'loss'}(s) in {count} archived game(s)."
            )
        else:
            per_game = metric.endswith("_per_game")
            component = metric[: -len("_per_game")] if per_game else metric
            numerator = totals[component]
            value = round(numerator / count, 1) if per_game else numerator
            unit = "points per game" if per_game else "points"
            decimals = 1 if per_game else 0
            label = _COMPONENT_LABELS[component]
            if component == "margin":
                statement = (
                    f"{group.label}: {value:+.1f} average {label} over {count} archived game(s)."
                    if per_game
                    else f"{group.label}: {value:+} total {label} over {count} archived game(s)."
                )
            else:
                statement = (
                    f"{group.label}: {value:.1f} {label} per game over {count} archived game(s)."
                    if per_game
                    else f"{group.label}: {value:g} total {label} over {count} archived game(s)."
                )
        claims.append(
            team_claim(
                tools,
                scope,
                population=games,
                metric=metric,
                value=value,
                unit=unit,
                statement=statement,
                games=games,
                evidence=evidence,
                numerator=numerator,
                decimals=decimals,
                eligibility=dict(eligibility),
                filters=_group_filters(scope, group),
                window=_group_window(scope, group, games),
                limitations=list(limitations),
                operation="team_comparison",
            )
        )
    return claims


def _bench_claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    group: ComparisonGroup,
    games: list[Game],
) -> VerifiedClaim:
    spec = scope.comparison
    assert spec is not None
    ids = {game.id for game in games}
    observed = [
        (stat, player)
        for stat, player in tools.rows
        if stat.game_id in ids and not stat.starter and stat.minutes > 0
    ]
    points = sum(stat.points for stat, _ in observed)
    # Every team game in the group is a denominator unit, including games where the
    # bench recorded nothing; the observed appearances only describe the numerator's rows.
    per_game = round(points / len(games), 1)
    statement = (
        f"{group.label}: {points} bench points across {len(games)} team games, "
        f"{per_game:.1f} per team game from {len(observed)} observed non-starter appearances."
    )
    evidence = [tools.receipt(game) for game in games]
    evidence.extend(
        tools.receipt(next(game for game in games if game.id == stat.game_id), stat, player)
        for stat, player in observed
    )
    eligibility = _group_eligibility(scope, group, games)
    eligibility.update(
        {
            "bench_definition": "observed rows with starter = false",
            "denominator_unit": "team games in the group",
        }
    )
    return team_claim(
        tools,
        scope,
        population=games,
        metric=team_claim_metrics(spec)[0],
        value=per_game,
        unit="points per game",
        statement=statement,
        games=games,
        evidence=evidence,
        sample=len(observed),
        denominator=len(games),
        numerator=points,
        decimals=1,
        eligibility=eligibility,
        filters=_group_filters(scope, group),
        window=_group_window(scope, group, games),
        limitations=[
            _COMPARISON_LIMITATION,
            "Bench points come from observed non-starter rows; a zero-minute row is not an "
            "appearance and a missing row is a coverage gap.",
        ],
        operation="team_comparison",
    )


def player_comparison_rows(
    tools: AnalystTools, scope: ResolvedQuery, group: ComparisonGroup, player_id: int
) -> tuple[list[tuple[PlayerGameStat, Any]], int]:
    """Window observed appearances before grouping, so a DNP consumes no slot.

    A group's own window applies after the shared appearance window.
    """
    spec = scope.comparison
    assert spec is not None
    order = {game.id: (game.game_date, game.id) for game in tools.games}
    pool_ids = {game.id for game in comparison_pool(spec, tools.games)}
    group_ids = {game.id for game in tools.comparison_populations(scope)[group.key]}
    rows = [
        (stat, player)
        for stat, player in tools.rows
        if stat.player_id == player_id and stat.game_id in pool_ids
    ]
    observed = sorted(
        ((stat, player) for stat, player in rows if stat.minutes > 0),
        key=lambda row: order[row[0].game_id],
    )
    if spec.filters.window is not None:
        observed = window_rows(observed, spec.filters.window)
    selected = [(stat, player) for stat, player in observed if stat.game_id in group_ids]
    if group.window is not None:
        selected = window_rows(selected, group.window)
    zero_minutes = sum(1 for stat, _ in rows if stat.minutes <= 0 and stat.game_id in group_ids)
    return selected, zero_minutes


def _unobserved_group(
    tools: AnalystTools, group: ComparisonGroup, games: list[Game], player_id: int
) -> str:
    """The coverage sentence for a group with team games and no observed player row."""
    name = next(
        (player.full_name for stat, player in tools.rows if stat.player_id == player_id),
        f"player {player_id}",
    )
    return (
        f"{name} has no observed box-score row for {group.label.lower()}: the archive does "
        f"not show whether they appeared in its {len(games)} game(s), so this group cannot "
        "be compared and the missing row is not evidence they did not play."
    )


_PERCENTAGE_COLUMNS = {
    "field_goal_percentage": ("field_goals_made", "field_goals_attempted"),
    "three_point_percentage": ("three_pointers_made", "three_pointers_attempted"),
    "free_throw_percentage": ("free_throws_made", "free_throws_attempted"),
}


def player_claim_metrics(spec: ComparisonSpec) -> frozenset[str]:
    """The exact metric ids one player group of this comparison can carry.

    `_player_claim` reads the same rules, so claim relevance validates against what the
    comparison emits instead of a list of every stat a player claim might ever name.
    """
    if spec.stat is None:
        aggregation = spec.aggregation or "average"
        return frozenset({f"{spec.metric or 'points'}:{aggregation}"})
    if STAT_REGISTRY[spec.stat].kind in {"count", "minutes"}:
        return frozenset({f"{spec.stat}:average", f"{spec.stat}:total"})
    return frozenset({metric_id_for(spec.stat)})


def _player_claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    group: ComparisonGroup,
    games: list[Game],
    player_id: int,
    metric: str,
) -> tuple[VerifiedClaim | None, str | None]:
    """One player's group claim, using the requested stat and aggregation.

    Returns the claim, or the honest coverage sentence when this group has no observed
    appearance or a rate has no denominator in it.
    """
    spec = scope.comparison
    assert spec is not None
    game_map = {game.id: game for game in tools.games}
    observed, zero_minutes = player_comparison_rows(tools, scope, group, player_id)
    if not observed:
        return None, _unobserved_group(tools, group, games, player_id)
    name = observed[0][1].full_name
    aggregation = spec.aggregation or "average"
    stat = spec.stat
    limitations = [
        "Only observed appearances in the available archive; a zero-minute row is not an "
        "appearance.",
        _COMPARISON_LIMITATION,
    ]
    if zero_minutes:
        limitations.append(f"{zero_minutes} archived game(s) in this group recorded zero minutes.")
    numerator: float | int | None = None
    eligibility: dict[str, Any] = {
        "operation": "player_comparison",
        "comparison_group": group.key,
        "comparison_kind": group.kind,
        "measure": "player_metric",
        "metric": stat or metric,
        "appearances": len(observed),
        "coverage": spec.coverage,
        "considered_games": len(games),
    }
    denominator: float | int | None = len(observed)
    if stat is not None:
        definition = STAT_REGISTRY[stat]
        kind = definition.kind
        eligibility["stat"] = stat
        eligibility["aggregation"] = aggregation
        if kind in {"count", "minutes"}:
            total = sum(
                float(getattr(stat_row, definition.columns[0], 0) or 0) for stat_row, _ in observed
            )
            value = total if aggregation == "total" else total / len(observed)
            numerator = total if aggregation == "average" else None
            if aggregation == "total":
                denominator = None
            claim_metric = f"{stat}:{aggregation}"
            unit = stat if aggregation == "total" else f"{stat} per appearance"
            decimals = 0 if aggregation == "total" else 1
            statement = (
                f"{name}, {group.label.lower()}: {int(value)} total {stat} across "
                f"{len(observed)} observed appearances."
                if aggregation == "total"
                else f"{name}, {group.label.lower()}: {value:.1f} {stat} per appearance "
                f"across {len(observed)} observed appearances ({int(total)} {stat})."
            )
        elif kind == "derived" and stat in {"double_doubles", "triple_doubles"}:
            value = aggregate_rows([row for row, _ in observed], [stat])[stat]
            claim_metric = metric_id_for(stat)
            unit = "count"
            decimals = 0
            statement = (
                f"{name}, {group.label.lower()}: {int(value or 0)} "
                f"{definition.label.lower()} across {len(observed)} observed appearances."
            )
        else:
            value = aggregate_rows([row for row, _ in observed], [stat])[stat]
            if value is None:
                denominator_word = "attempt count" if kind == "percentage" else "denominator"
                return None, (
                    f"{name}'s {definition.label.lower()} is undefined for "
                    f"{group.label.lower()}: the {denominator_word} is zero across "
                    f"{len(observed)} observed appearances, so no ratio is reported."
                )
            claim_metric = metric_id_for(stat)
            unit = "percent" if kind == "percentage" else "ratio"
            decimals = 1 if kind == "percentage" else 2
            statement = (
                f"{name}, {group.label.lower()}: {definition.label.lower()} of "
                f"{value:.{decimals}f} across {len(observed)} observed appearances."
            )
            columns = _PERCENTAGE_COLUMNS.get(stat)
            if columns is not None:
                made_column, attempted_column = columns
                made = sum(getattr(row, made_column) for row, _ in observed)
                attempted = sum(getattr(row, attempted_column) for row, _ in observed)
                eligibility["made"] = made
                eligibility["attempted"] = attempted
    else:
        total = sum(getattr(stat_row, metric) for stat_row, _ in observed)
        value = total if aggregation == "total" else total / len(observed)
        numerator = total if aggregation == "average" else None
        if aggregation == "total":
            denominator = None
        claim_metric = f"{metric}:{aggregation}"
        unit = metric if aggregation == "total" else f"{metric} per appearance"
        decimals = 0 if aggregation == "total" else 1
        statement = (
            f"{name}, {group.label.lower()}: {int(value)} total {metric} across "
            f"{len(observed)} observed appearances."
            if aggregation == "total"
            else f"{name}, {group.label.lower()}: {value:.1f} {metric} per appearance "
            f"across {len(observed)} observed appearances ({int(total)} {metric})."
        )
    evidence = [
        tools.receipt(game_map[stat_row.game_id], stat_row, player) for stat_row, player in observed
    ]
    claim_games = [game_map[row.game_id] for row, _ in observed]
    claim = tools.claim(
        subject=f"player:{player_id}",
        metric=claim_metric,
        value=value,
        unit=unit,
        games=claim_games,
        evidence=evidence,
        statement=statement,
        scope=scope,
        sample=len(observed),
        denominator=denominator,
        numerator=numerator,
        decimals=decimals,
        eligibility=eligibility,
        window=_group_window(scope, group, claim_games),
        operation="player_comparison",
        considered_game_ids=[game.id for game in games],
        filters=_group_filters(scope, group),
        limitations=limitations,
    )
    return claim, None


async def compare(tools: AnalystTools, scope: ResolvedQuery) -> ToolResult:
    """Answer every group of one typed comparison from its own considered games."""
    spec: ComparisonSpec | None = scope.comparison
    if spec is None:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="That request is not a grouped comparison.",
            scope=scope.model_dump(mode="json"),
        )
    populations = tools.comparison_populations(scope)
    ordered = [(group, populations[group.key]) for group in spec.groups]
    empty = [group.key for group, games in ordered if not games]
    answered: list[str] = []
    claims: list[VerifiedClaim] = []
    undefined: list[str] = []
    for group, games in ordered:
        if not games:
            continue
        before = len(claims)
        if spec.measure == "scoring":
            claims.extend(_team_claims(tools, scope, group, games))
        elif spec.measure == "bench_points":
            claims.append(_bench_claim(tools, scope, group, games))
        else:
            for player_id in scope.player_ids:
                claim, missing = _player_claim(
                    tools, scope, group, games, player_id, spec.metric or "points"
                )
                if claim is not None:
                    claims.append(claim)
                elif missing is not None:
                    undefined.append(missing)
        if len(claims) > before:
            answered.append(group.key)
    coverage = " ".join(undefined)
    if not claims:
        message = (
            f"No archived games match {', '.join(empty)}; this is not evidence that no "
            "such games occurred."
            if empty
            else "No archived population matches this comparison."
        )
        if coverage:
            message = f"{message} {coverage}"
        return ToolResult(
            status="incomplete_coverage",
            message=message,
            evidence=[tools.receipt(game) for game in tools.games],
            scope=scope.model_dump(mode="json"),
        )
    evidence: dict[str, Any] = {}
    for claim in claims:
        for ref in claim.supporting_evidence_ids:
            evidence.setdefault(ref, tools.evidence[ref])
    message = (
        f"Compared {len(answered)} group(s) from their own populations; retrieval is not a "
        "denominator."
    )
    if empty:
        message += f" No archived games match {', '.join(empty)} in this coverage."
    if coverage:
        message += f" {coverage}"
    return ToolResult(
        status="incomplete_coverage" if empty or coverage else "ok",
        message=message,
        claims=claims,
        evidence=list(evidence.values()),
        scope=scope.model_dump(mode="json"),
    )
