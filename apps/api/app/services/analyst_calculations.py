"""Analyst calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.game import Game
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import ResolvedQuery, is_record_request

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


def player(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game], metric: str, aggregation: str
) -> ToolResult:
    if scope.relative_game_count and "appearance" not in tools.question.lower():
        games = games[-scope.relative_game_count :]
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
            rows = rows[-scope.relative_game_count :]
        if not rows:
            continue
        count = len(rows)
        value = sum(getattr(s, metric) for s, _ in rows)
        if aggregation == "average":
            value /= count
        receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in rows]
        evidence.extend(receipts)
        limitations = ["Only observed appearances in the available archive."]
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


def team(tools: AnalystTools, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
    if is_record_request(tools.question):
        games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
    if scope.relative_game_count:
        games = games[-scope.relative_game_count :]
    evidence = [tools.receipt(g) for g in games]
    wins = sum(tools.score(g)[0] > tools.score(g)[1] for g in games)
    values = {
        "wins": wins,
        "losses": len(games) - wins,
        "points": sum(tools.score(g)[0] for g in games),
        "margin": sum(tools.score(g)[0] - tools.score(g)[1] for g in games),
    }
    claims = [
        tools.claim(
            subject="team:NYK",
            metric=metric,
            value=value,
            unit=metric,
            games=games,
            evidence=evidence,
            scope=scope,
            sample=len(games),
            denominator=None,
            eligibility={"game": "archived Knicks game"},
            statement=f"Knicks {metric}: {value} over {len(games)} archived games.",
        )
        for metric, value in values.items()
    ]
    return ToolResult(
        status="ok",
        message="Archive team totals.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
