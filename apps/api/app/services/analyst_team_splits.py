"""Counting and split operations: numeric cutoffs, period scoring, win/loss splits."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.models.box_score import PeriodScore, TeamGameStat
from app.models.game import Game
from app.services.analyst_claim_support import team_claim
from app.services.analyst_player_stats import metric_id_for
from app.services.analyst_provenance import (
    period_projection,
    row_receipt,
    team_stat_projection,
)
from app.services.evidence_contracts import Evidence, ToolResult
from app.services.query_operations import PERCENTAGE_STATS, ThresholdSpec
from app.services.query_resolution import ResolvedQuery
from basketball_core.analytics.calculations import aggregate_rows
from basketball_core.analytics.registry import STAT_REGISTRY
from sqlalchemy import select

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

_PERIOD_NAMES = {1: "first", 2: "second", 3: "third", 4: "fourth"}
_SUBJECT_SENTENCES = {
    "own_points": "the Knicks scored {phrase}",
    "opponent_points": "opponents scored {phrase}",
    "margin": "the Knicks won by {phrase}",
    "deficit": "the Knicks lost by {phrase}",
}


_PERCENTAGE_COLUMNS = {
    "field_goal_percentage": ("field_goals_made", "field_goals_attempted"),
    "three_point_percentage": ("three_pointers_made", "three_pointers_attempted"),
    "free_throw_percentage": ("free_throws_made", "free_throws_attempted"),
}
_DISTANCE = {
    "three_point_percentage": "from three",
    "free_throw_percentage": "at the line",
}


def _row_evidence(
    tools: AnalystTools,
    game: Game,
    row: Any,
    *,
    collection: str,
    canonical_id: str,
    project: Callable[[Game, Any], dict[str, Any]],
) -> Evidence:
    """One private receipt for the SQL row a period or team measure read."""
    identity = row_receipt(tools.release.version, collection, game.id, row.id)
    existing = tools.evidence.get(identity)
    if existing is not None:
        return existing
    data = project(game, row)
    evidence = Evidence(
        evidence_id=identity,
        release_id=tools.release.version,
        game_id=game.id,
        text=json.dumps(data, sort_keys=True),
        source_name=game.source_name,
        source_url=game.source_url,
        metadata={"date": str(game.game_date), "team_id": row.team_id},
    )
    tools.evidence[identity] = evidence
    tools.provenance.capture_row(
        identity,
        collection=collection,
        canonical_id=canonical_id,
        row=data,
        source_row_id=row.id,
    )
    return evidence


def _qualifies(tools: AnalystTools, game: Game, spec: ThresholdSpec) -> bool:
    """Whether one final score crosses the cutoff for the requested subject.

    A margin cutoff requires a win and a deficit cutoff requires a loss; the signed
    difference alone would count the opposite outcome through its negative value.
    """
    own, other = tools.score(game)
    if spec.subject == "own_points":
        measured = own
    elif spec.subject == "opponent_points":
        measured = other
    elif spec.subject == "margin":
        if own <= other:
            return False
        measured = own - other
    else:
        if other <= own:
            return False
        measured = other - own
    return spec.accepts(measured)


def threshold_count(
    tools: AnalystTools, scope: ResolvedQuery, population: list[Game]
) -> ToolResult:
    """Count the games in the complete considered population that cross one cutoff."""
    spec = scope.threshold
    if spec is None:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="That count needs a numeric cutoff.",
            scope=scope.model_dump(mode="json"),
        )
    matching = [game for game in population if _qualifies(tools, game, spec)]
    population_receipts = [tools.receipt(game) for game in population]
    sentence = _SUBJECT_SENTENCES[spec.subject].format(phrase=spec.describe())
    statement = (
        f"In {len(matching)} of {len(population)} archived {tools.release.season} games, "
        f"{sentence}."
    )
    claim = team_claim(
        tools,
        scope,
        population=population,
        metric="games",
        value=len(matching),
        unit="games",
        statement=statement,
        games=matching,
        # Evidence describes the considered population, so a valid zero-count answer
        # still cites the denominator instead of arriving with no support at all.
        evidence=population_receipts,
        sample=len(matching),
        denominator=len(population),
        eligibility={
            "subject": spec.subject,
            "comparator": spec.comparator,
            "threshold": spec.value,
            "matching_game_ids": [game.id for game in matching],
        },
        limitations=[
            "Counted over every archived game this scope admits; retrieval is not the denominator.",
            "Final scores only; a game without a final score is not counted.",
        ],
    )
    return ToolResult(
        status="ok",
        message=(
            f"Counted {len(matching)} of {len(population)} considered games; the denominator is "
            "the complete considered population."
        ),
        claims=[claim],
        evidence=population_receipts,
        scope=scope.model_dump(mode="json"),
    )


async def period_scoring(tools: AnalystTools, scope: ResolvedQuery) -> ToolResult:
    """Report Knicks scoring per requested period over the considered games."""
    population = tools.considered_games(scope)
    if not population:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence that no such "
            "games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    game_by_id = {game.id: game for game in population}
    stmt = (
        select(PeriodScore)
        .where(
            PeriodScore.release_id == tools.release.id,
            PeriodScore.game_id.in_(list(game_by_id)),
            PeriodScore.team_id == "NYK",
        )
        .order_by(PeriodScore.game_id, PeriodScore.period)
    )
    if scope.periods:
        stmt = stmt.where(PeriodScore.period.in_(scope.periods))
    rows = list((await tools.db.execute(stmt)).scalars())
    if not rows:
        return ToolResult(
            status="incomplete_coverage",
            message="No stored period scores are available for these games.",
            evidence=[tools.receipt(game) for game in population],
            scope=scope.model_dump(mode="json"),
        )
    by_period: dict[int, list[PeriodScore]] = {}
    for row in rows:
        by_period.setdefault(int(row.period), []).append(row)
    claims = []
    row_evidence: list[Evidence] = []
    for period in sorted(by_period):
        period_rows = by_period[period]
        total = sum(int(row.points) for row in period_rows)
        games_covered = len(period_rows)
        name = _PERIOD_NAMES.get(period, f"period {period}")
        covered_games = [game_by_id[row.game_id] for row in period_rows]
        receipts = [
            _row_evidence(
                tools,
                game_by_id[row.game_id],
                row,
                collection="period_scores",
                canonical_id=f"period:{game_by_id[row.game_id].nba_game_id}:{row.team_id}:{period}",
                project=period_projection,
            )
            for row in period_rows
        ]
        row_evidence.extend(receipts)
        limitations = [
            "Stored period totals only; they are not possession or rotation context.",
        ]
        if games_covered != len(population):
            limitations.append(
                f"Period rows cover {games_covered} of {len(population)} considered games."
            )
        claims.append(
            team_claim(
                tools,
                scope,
                population=population,
                metric="period:points",
                value=total / games_covered,
                unit="points per game",
                statement=(
                    f"The Knicks averaged {total / games_covered:.1f} {name}-quarter points "
                    f"across {games_covered} archived {tools.release.season} games."
                ),
                games=covered_games,
                evidence=receipts,
                sample=games_covered,
                denominator=games_covered,
                numerator=total,
                eligibility={"period": period, "period_points": total},
                filters={"periods": [period]},
                limitations=limitations,
            )
        )
    missing = sorted(set(scope.periods) - set(by_period))
    if missing:
        return ToolResult(
            status="incomplete_coverage",
            message=f"No stored period scores for periods {missing}.",
            claims=claims,
            evidence=row_evidence,
            scope=scope.model_dump(mode="json"),
        )
    return ToolResult(
        status="ok",
        message=(
            f"Averaged {len(by_period)} requested period(s) over {len(population)} considered "
            "games; retrieval is not the denominator."
        ),
        claims=claims,
        evidence=row_evidence,
        scope=scope.model_dump(mode="json"),
    )


async def result_split(tools: AnalystTools, scope: ResolvedQuery) -> ToolResult:
    """Compare one team measure across the wins and the losses in one population."""
    population = tools.considered_games(scope)
    if not population:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope; this is not evidence that no such "
            "games occurred.",
            scope=scope.model_dump(mode="json"),
        )
    sides = {
        "win": [game for game in population if tools.score(game)[0] > tools.score(game)[1]],
        "loss": [game for game in population if tools.score(game)[0] < tools.score(game)[1]],
    }
    stat = scope.stat or ""
    per_game = scope.aggregation != "total"
    claims = []
    row_evidence: list[Evidence] = []
    uncovered: list[str] = []
    for side, games in sides.items():
        if not games:
            continue
        label = "wins" if side == "win" else "losses"
        if stat == "margin":
            # A point-differential split measures each side's own signed margin from the
            # same final scores; it never reuses a stored count column.
            total_margin = sum(own - other for own, other in (tools.score(game) for game in games))
            value = total_margin / len(games) if per_game else total_margin
            metric = f"margin:{'average' if per_game else 'total'}"
            claims.append(
                team_claim(
                    tools,
                    scope,
                    population=population,
                    metric=metric,
                    value=round(value, 4) if isinstance(value, float) else value,
                    unit="points per game" if per_game else "points",
                    statement=(
                        f"In {label} the Knicks' average margin was {value:+.1f} points across "
                        f"{len(games)} archived {tools.release.season} games."
                        if per_game
                        else f"In {label} the Knicks' combined margin was {int(value):+d} points "
                        f"across {len(games)} archived {tools.release.season} games."
                    ),
                    games=games,
                    evidence=[tools.receipt(game) for game in games],
                    sample=len(games),
                    denominator=len(games),
                    numerator=total_margin if per_game else None,
                    decimals=1 if per_game else None,
                    eligibility={"result": side, "total_margin": total_margin},
                    filters={"game_result": side},
                    limitations=[
                        "Split by final result; the archive stores no lineup or possession splits.",
                        "Retrieval is not the denominator.",
                    ],
                )
            )
            continue
        game_ids = [game.id for game in games]
        game_by_id = {game.id: game for game in games}
        rows = (
            await tools.db.execute(
                select(TeamGameStat).where(
                    TeamGameStat.release_id == tools.release.id,
                    TeamGameStat.game_id.in_(game_ids),
                    TeamGameStat.team_id == "NYK",
                )
            )
        ).scalars()
        stored = list(rows)
        if not stored:
            uncovered.append(side)
            continue
        covered_games = [game_by_id[row.game_id] for row in stored]
        receipts = [
            _row_evidence(
                tools,
                game_by_id[row.game_id],
                row,
                collection="team_game_stats",
                canonical_id=f"team_box:{game_by_id[row.game_id].nba_game_id}:{row.team_id}",
                project=team_stat_projection,
            )
            for row in stored
        ]
        row_evidence.extend(receipts)
        limitations = [
            "Split by final result; the archive stores no lineup or possession splits.",
            "Retrieval is not the denominator.",
        ]
        if len(stored) != len(games):
            limitations.append(
                f"Team box rows cover {len(stored)} of {len(games)} games in this split."
            )
        numerator = None
        if stat in PERCENTAGE_STATS:
            columns = _PERCENTAGE_COLUMNS.get(stat)
            if columns is not None:
                made_column, attempted_column = columns
                made = sum(getattr(row, made_column) for row in stored)
                attempted = sum(getattr(row, attempted_column) for row in stored)
                if not attempted:
                    uncovered.append(side)
                    continue
                value = 100.0 * made / attempted
                eligibility = {"result": side, "made": made, "attempted": attempted}
                distance = _DISTANCE.get(stat, "from the field")
                statement = (
                    f"In {label} the Knicks shot {value:.1f} percent {distance} across "
                    f"{len(stored)} archived {tools.release.season} games."
                )
            else:
                value = aggregate_rows(stored, [stat])[stat]
                if value is None:
                    uncovered.append(side)
                    continue
                eligibility = {"result": side}
                statement = (
                    f"In {label} the Knicks recorded a "
                    f"{STAT_REGISTRY[stat].label.lower()} of {value:.1f} percent across "
                    f"{len(stored)} archived {tools.release.season} games."
                )
            metric = metric_id_for(stat)
            unit = "percent"
        else:
            metric_key = scope.metric or "points"
            total = sum(getattr(row, metric_key) for row in stored)
            value = total / len(stored) if per_game else total
            numerator = total if per_game else None
            metric = f"{metric_key}:{'average' if per_game else 'total'}"
            unit = f"{metric_key} per game" if per_game else metric_key
            statement = (
                f"In {label} the Knicks averaged {value:.1f} {metric_key} per game across "
                f"{len(stored)} archived {tools.release.season} games."
                if per_game
                else f"In {label} the Knicks recorded {int(value)} total {metric_key} across "
                f"{len(stored)} archived {tools.release.season} games."
            )
            eligibility = {"result": side, "total": total}
        claims.append(
            team_claim(
                tools,
                scope,
                population=population,
                metric=metric,
                value=round(value, 4) if isinstance(value, float) else value,
                unit=unit,
                statement=statement,
                games=covered_games,
                evidence=receipts,
                sample=len(stored),
                denominator=len(stored),
                numerator=numerator,
                decimals=4 if (numerator is not None or stat in PERCENTAGE_STATS) else None,
                eligibility=eligibility,
                filters={"game_result": side},
                limitations=limitations,
            )
        )
    if not claims:
        return ToolResult(
            status="incomplete_coverage",
            message="No stored team box score covers this split.",
            evidence=[tools.receipt(game) for game in population],
            scope=scope.model_dump(mode="json"),
        )
    return ToolResult(
        status="incomplete_coverage" if uncovered else "ok",
        message=(
            f"Split {len(population)} considered games by final result; "
            + (
                f"no stored rows for {uncovered}."
                if uncovered
                else "retrieval is not the denominator."
            )
        ),
        claims=claims,
        evidence=row_evidence or [tools.receipt(game) for game in population],
        scope=scope.model_dump(mode="json"),
    )
