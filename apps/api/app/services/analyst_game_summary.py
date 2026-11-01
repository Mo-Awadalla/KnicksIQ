"""Verified player statlines and final scores for one pinned archive game."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.game import Game
from app.services.analyst_player_stats import observed_appearances
from app.services.evidence_contracts import ToolResult
from app.services.query_operations import GAME_SCORE_METRIC, GAME_SUMMARY_STATS
from app.services.query_resolution import ResolvedQuery

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

_GAME_SUMMARY_LIMITATION = (
    "One archived game's own box-score row; box-score totals only, with no play-by-play."
)


def _one_game(scope: ResolvedQuery, games: list[Game]) -> ToolResult | None:
    """The single pinned game a one-game statline may stand for, or the honest refusal."""
    if len(games) == 1:
        return None
    if not games:
        return ToolResult(
            status="no_matching_results",
            message="No archived game matches this scope; this is not evidence that no such "
            "game occurred.",
            scope=scope.model_dump(mode="json"),
        )
    return ToolResult(
        status="ambiguous_entity",
        message="A one-game statline needs exactly one archived game. Which game do you mean?",
        choices=[
            f"{game.game_date}: {game.away_team_id} at {game.home_team_id}" for game in games[:8]
        ],
        scope=scope.model_dump(mode="json"),
    )


def game_summary(tools: AnalystTools, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
    """One pinned game's own box-score line, plus that game's final score.

    A broad performance ask names no measure, so it is answered from the game's own row
    (points, rebounds and assists) and the game's verified final score. The population is
    that one game: several matching games are the user's choice, never a silent pick, and a
    player with no observed appearance contributes no invented zero line.
    """
    unresolved = _one_game(scope, games)
    if unresolved is not None:
        return unresolved
    if not scope.player_ids:
        return ToolResult(
            status="ambiguous_entity",
            message="Which Knicks player?",
            choices=sorted({p.full_name for _, p in tools.rows}),
            scope=scope.model_dump(mode="json"),
        )
    game = games[0]
    game_map = {game.id: game}
    claims, evidence, notes = [], [], []
    missing = False
    for player_id in scope.player_ids:
        observed, absent, dropped = observed_appearances(tools, player_id, game_map)
        name = next(
            (p.full_name for _, p in tools.rows if p.id == player_id), f"player {player_id}"
        )
        if not observed:
            missing = True
            if absent:
                notes.append(
                    f"The archive has no box-score row for {name} in the {game.game_date} game."
                )
            else:
                notes.append(
                    f"{name} is recorded with zero minutes in the {game.game_date} game, "
                    "which is not an appearance."
                )
            continue
        if dropped:
            notes.append(
                f"{name} has {dropped} archived row(s) with zero minutes that are not appearances."
            )
        row, player = observed[0]
        receipt = tools.receipt(game, row, player)
        evidence.append(receipt)
        for stat in GAME_SUMMARY_STATS:
            value = int(getattr(row, stat))
            claims.append(
                tools.claim(
                    subject=f"player:{player_id}",
                    metric=f"{stat}:game",
                    value=value,
                    unit=stat,
                    games=[game],
                    evidence=[receipt],
                    statement=(
                        f"{player.full_name}: {value} {stat} in the "
                        f"{game.game_date} {game.away_team_id} at {game.home_team_id} game."
                    ),
                    scope=scope,
                    sample=1,
                    denominator=1,
                    limitations=[_GAME_SUMMARY_LIMITATION],
                    operation="player_game_summary",
                    considered_game_ids=[game.id],
                )
            )
    if claims:
        # The scoreline is a fact about the game itself, and it is already the verified row
        # every statline receipt cites; it is never the answer to a player question alone.
        claims.append(
            tools.claim(
                subject="team:NYK",
                metric=GAME_SCORE_METRIC,
                value={
                    "nba_game_id": game.nba_game_id,
                    "game_date": game.game_date.isoformat(),
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                },
                unit="scoreline",
                games=[game],
                evidence=[tools.receipt(game)],
                statement=(
                    f"Final score on {game.game_date}: {game.away_team_id} "
                    f"{game.away_score}, {game.home_team_id} {game.home_score}."
                ),
                scope=scope,
                sample=1,
                denominator=None,
                limitations=[_GAME_SUMMARY_LIMITATION],
                operation="player_game_summary",
                considered_game_ids=[game.id],
            )
        )
    coverage = " ".join(dict.fromkeys(notes))
    if claims and coverage:
        message = (
            "One archived game's own box-score row; retrieval is not the denominator. " + coverage
        )
    elif coverage:
        message = coverage
    elif claims:
        message = "One archived game's own box-score row; retrieval is not the denominator."
    else:
        message = "No observed player appearance in that archived game."
    return ToolResult(
        status=("incomplete_coverage" if missing else "ok") if claims else "no_matching_results",
        message=message,
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
