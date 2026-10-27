"""get_game_narrative handler: canonical selected-game stories and their score receipts."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.canonical_narrative import build_narrative
from app.services.evidence_contracts import Evidence, ToolResult

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from app.services.query_resolution import ResolvedQuery


def _score_comparison(tools: AnalystTools, game: Game) -> tuple[list[Evidence], dict[str, Any]]:
    assert tools.narrative is not None
    population = tools.narrative.comparison_games
    comparison = {
        "definition": tools.narrative.definition,
        "game_ids": [compared.id for compared in population],
        "selected_game_ids": [selected.id for selected in tools.narrative.games],
        "sample_size": len(population),
        "season_types": sorted({compared.season_type for compared in population}),
    }
    # Keep the selected game's source first so equal tied scores retain
    # distinct calculation receipts while every eligible source is included.
    evidence = [tools.receipt(game)]
    evidence.extend(tools.receipt(compared) for compared in population if compared.id != game.id)
    return evidence, comparison


def _game_score(tools: AnalystTools, scope: ResolvedQuery, game: Game) -> ToolResult:
    if game.status != "final":
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="A final score is not available for this archived game.",
        )
    evidence = [tools.receipt(game)]
    knicks, opponent = tools.score(game)
    opponent_id = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
    statement = f"Final score on {game.game_date}: NYK {knicks}, {opponent_id} {opponent}."
    eligibility: dict[str, Any] = {"game": "final archived Knicks game"}
    if tools.narrative and tools.statistical_extreme_requested():
        evidence, comparison = _score_comparison(tools, game)
        eligibility["comparison"] = comparison
        statement = (
            f"Selection measure: {tools.narrative.definition} "
            f"Compared archive phases: {', '.join(comparison['season_types'])}. {statement}"
        )
    claim = tools.claim(
        subject="team:NYK",
        metric="game_score",
        value={"NYK": knicks, opponent_id: opponent},
        unit="points by team",
        games=[game],
        evidence=evidence,
        scope=scope,
        sample=1,
        denominator=None,
        eligibility=eligibility,
        statement=statement,
    )
    return ToolResult(
        status="ok",
        message="Archived final score.",
        claims=[claim],
        evidence=[tools.evidence[ref] for ref in claim.supporting_evidence_ids],
        scope=scope.model_dump(mode="json"),
    )


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    if scope.requires_clarification:
        return ToolResult(
            status="ambiguous_entity",
            message="Which subject did you mean?",
            choices=scope.clarification_options,
        )
    if (
        tools.season != tools.release.season
        or re.search(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        and any(
            season != tools.release.season
            for season in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", tools.question)
        )
    ):
        return ToolResult(
            status="unsupported_metric_or_scope",
            message=f"Available season: {tools.release.season}.",
        )
    if not tools.narrative:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="A defined game-story selection is required.",
        )
    if tools.statistical_extreme_requested():
        results = []
        for game in tools.narrative.games:
            game_scope = scope.model_copy(update={"game_ids": [game.id]})
            score_result = _game_score(tools, game_scope, game)
            results.append(score_result)
            if "margin" in tools.question.lower():
                own, opponent = tools.score(game)
                comparison = score_result.claims[0].eligibility["comparison"]
                claim = tools.claim(
                    subject="team:NYK",
                    metric="margin",
                    value=own - opponent,
                    unit="points",
                    games=[game],
                    evidence=score_result.evidence,
                    scope=game_scope,
                    sample=1,
                    denominator=None,
                    eligibility={
                        "selection": tools.narrative.definition,
                        "comparison": comparison,
                    },
                    statement=(
                        f"Knicks final scoring margin on {game.game_date}: {own - opponent} points."
                    ),
                )
                results.append(
                    ToolResult(status="ok", message="Selected final margin.", claims=[claim])
                )
        return ToolResult(
            status="ok",
            message=tools.narrative.definition,
            claims=[c for r in results for c in r.claims],
            evidence=[e for r in results for e in r.evidence],
            scope=scope.model_dump(mode="json"),
        )
    return await build_narrative(tools.db, tools.release, tools.narrative)
