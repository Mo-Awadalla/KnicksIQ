"""Team claim provenance shared by the team operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.game import Game
from app.services.evidence_contracts import Evidence, VerifiedClaim
from app.services.query_resolution import ResolvedQuery

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

CALCULATION_LIMITATIONS = ["Available archive only; no causal inference."]


def opponent(game: Game) -> str:
    return game.away_team_id if game.home_team_id == "NYK" else game.home_team_id


def margin(tools: AnalystTools, game: Game) -> int:
    own, other = tools.score(game)
    return own - other


def team_claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    *,
    population: list[Game],
    metric: str,
    value: float | int | dict[str, Any],
    unit: str,
    statement: str,
    games: list[Game],
    evidence: list[Evidence],
    limitations: list[str] | None = None,
    eligibility: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    sample: int | None = None,
    denominator: float | int | None = None,
    numerator: float | int | None = None,
    decimals: int | None = None,
    operation: str | None = None,
    window: dict[str, Any] | None = None,
) -> VerifiedClaim:
    """Record one team claim with the operation and the complete considered population."""
    return tools.claim(
        subject="team:NYK",
        metric=metric,
        value=value,
        unit=unit,
        games=games,
        evidence=evidence,
        statement=statement,
        scope=scope,
        sample=len(population) if sample is None else sample,
        denominator=(
            (len(population) if metric.endswith("_per_game") else None)
            if denominator is None
            else denominator
        ),
        limitations=limitations or list(CALCULATION_LIMITATIONS),
        eligibility={"game": "archived Knicks game", **(eligibility or {})},
        operation=operation or scope.operation or "team_aggregate",
        considered_game_ids=[game.id for game in population],
        filters=filters,
        numerator=numerator,
        decimals=decimals,
        window=(
            {
                "date_start": str(population[0].game_date),
                "date_end": str(population[-1].game_date),
                "considered_games": len(population),
            }
            | (window or {})
        )
        if population
        else window,
    )
