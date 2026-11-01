"""Ranking operations: score and margin extremes, streaks and score-margin swings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.analyst_claim_support import margin, opponent, team_claim
from app.services.evidence_contracts import ToolResult
from app.services.query_resolution import ResolvedQuery
from sqlalchemy import func, select

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

SCORING_EXTREMES = frozenset({"highest_scoring_game", "lowest_scoring_game"})
MARGIN_EXTREMES = frozenset({"largest_win_margin", "largest_loss_margin"})
DEFENSIVE_EXTREME = frozenset({"lowest_opponent_points_game"})
STREAK_LABELS = {
    "longest_losing_streak": "losing",
    "longest_winning_streak": "winning",
}


def _extreme_games(
    tools: AnalystTools, population: list[Game], operation: str | None
) -> tuple[int, list[Game]]:
    """Return the extreme value and every game that reached it."""
    if operation in MARGIN_EXTREMES:
        sign = 1 if operation == "largest_win_margin" else -1
        scored = [(sign * margin(tools, game), game) for game in population]
        scored = [(value, game) for value, game in scored if value > 0]
    elif operation in DEFENSIVE_EXTREME:
        scored = [(tools.score(game)[1], game) for game in population]
    else:
        scored = [(tools.score(game)[0], game) for game in population]
    if not scored:
        return 0, []
    pool = [value for value, _ in scored]
    target = (
        min(pool)
        if operation == "lowest_scoring_game" or operation in (DEFENSIVE_EXTREME)
        else max(pool)
    )
    picked = sorted(
        (game for value, game in scored if value == target),
        key=lambda game: (game.game_date, game.id),
    )
    return int(target), picked


def extremes(tools: AnalystTools, scope: ResolvedQuery, population: list[Game]) -> ToolResult:
    operation = scope.operation
    season = tools.release.season
    value, picked = _extreme_games(tools, population, operation)
    if not picked:
        return ToolResult(
            status="no_matching_results",
            message=f"No qualifying {season} game in the considered population.",
            scope=scope.model_dump(mode="json"),
        )
    claims = []
    for index, game in enumerate(picked):
        own, other = tools.score(game)
        opponent_id = opponent(game)
        if operation in MARGIN_EXTREMES:
            metric = "win_margin" if operation == "largest_win_margin" else "loss_margin"
            label = "largest win" if operation == "largest_win_margin" else "largest loss"
            headline = (
                f"The Knicks' {label} in the available {season} archive was {game.game_date} "
                f"against {opponent_id}: NYK {own}, {opponent_id} {other}, "
                f"a {value}-point margin."
            )
            if index:
                headline = (
                    f"The same {value}-point margin also occurred on {game.game_date} "
                    f"against {opponent_id}: NYK {own}, {opponent_id} {other}."
                )
        elif operation in DEFENSIVE_EXTREME:
            metric = "opponent_points"
            headline = (
                f"The Knicks' best defensive game in the available {season} archive was "
                f"{game.game_date} against {opponent_id}: NYK {own}, {opponent_id} {other}, "
                f"{value} points allowed."
            )
            if index:
                headline = (
                    f"The same {value} points allowed also occurred on {game.game_date} "
                    f"against {opponent_id}: NYK {own}, {opponent_id} {other}."
                )
        else:
            metric = "points"
            label = "highest-scoring" if operation == "highest_scoring_game" else "lowest-scoring"
            headline = (
                f"The Knicks' {label} game in the available {season} archive was "
                f"{game.game_date} against {opponent_id}: NYK {own}, {opponent_id} {other}."
            )
            if index:
                headline = (
                    f"The same {value} points also occurred on {game.game_date} "
                    f"against {opponent_id}: NYK {own}, {opponent_id} {other}."
                )
        claims.append(
            team_claim(
                tools,
                scope,
                population=population,
                metric=metric,
                value=value,
                unit="points",
                statement=headline,
                games=[game],
                evidence=[tools.receipt(game)],
                limitations=[
                    f"Selected as the extreme of {len(population)} considered games; "
                    "selection is not proof of a trend.",
                    "Final scores only; no possession or rotation context.",
                ],
            )
        )
    return ToolResult(
        status="ok",
        message=f"Ranked {len(population)} considered games; all tied games are included.",
        claims=claims,
        evidence=[tools.receipt(game) for game in picked],
        scope=scope.model_dump(mode="json"),
    )


def _runs(tools: AnalystTools, population: list[Game], operation: str) -> list[list[Game]]:
    losing = operation == "longest_losing_streak"
    runs: list[list[Game]] = []
    current: list[Game] = []
    for game in population:
        value = margin(tools, game)
        matches = value < 0 if losing else value > 0
        if matches:
            current.append(game)
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def streaks(tools: AnalystTools, scope: ResolvedQuery, population: list[Game]) -> ToolResult:
    operation = scope.operation or ""
    label = STREAK_LABELS[operation]
    runs = _runs(tools, population, operation)
    if not runs:
        return ToolResult(
            status="no_matching_results",
            message=(f"The available {tools.release.season} archive contains no {label} streak."),
            evidence=[tools.receipt(g) for g in population],
            scope=scope.model_dump(mode="json"),
        )
    longest = max(len(run) for run in runs)
    tied = [run for run in runs if len(run) == longest]
    claims = []
    if len(tied) == 1:
        run = tied[0]
        summary = (
            f"The Knicks' longest {label} streak in the available {tools.release.season} "
            f"archive was {longest} games, from {run[0].game_date} through {run[-1].game_date}."
        )
    else:
        summary = (
            f"The Knicks' longest {label} streak in the available {tools.release.season} "
            f"archive was {longest} games, which happened {len(tied)} times."
        )
    claims.append(
        team_claim(
            tools,
            scope,
            population=population,
            metric=f"{label}_streak_length",
            value=longest,
            unit="games",
            statement=summary,
            games=[game for run in tied for game in run],
            evidence=[tools.receipt(game) for run in tied for game in run],
            limitations=[
                "Streaks are consecutive in the available archive; a missing game could "
                "split or join a run.",
                "Ranking includes every tied streak, not only the first.",
            ],
        )
    )
    for run in tied:
        span = (
            f"on {run[0].game_date}"
            if len(run) == 1
            else f"from {run[0].game_date} through {run[-1].game_date}"
        )
        claims.append(
            team_claim(
                tools,
                scope,
                population=population,
                metric=f"{label}_streak",
                value=longest,
                unit="games",
                statement=f"A {longest}-game {label} streak ran {span}.",
                games=run,
                evidence=[tools.receipt(game) for game in run],
                limitations=[
                    "Consecutive archived games only; the archive is not a complete season.",
                ],
            )
        )
    return ToolResult(
        status="ok",
        message=(
            f"Scanned {len(population)} considered games in order; every tied streak is reported."
        ),
        claims=claims,
        evidence=[tools.receipt(game) for run in tied for game in run],
        scope=scope.model_dump(mode="json"),
    )


async def swings(tools: AnalystTools, scope: ResolvedQuery) -> ToolResult:
    """Rank games by the observed range of the Knicks' score margin.

    The range includes a zero anchor, so a game the Knicks trailed throughout is measured
    from its largest deficit to a tie, exactly like the archive's swing ranking.
    """
    games = tools.considered_games(scope)
    if not games:
        return ToolResult(
            status="no_matching_results",
            message="No archived games match this scope.",
            scope=scope.model_dump(mode="json"),
        )
    game_map = {game.id: game for game in games}
    rows = (
        await tools.db.execute(
            select(
                GameEvent.game_id,
                func.min(GameEvent.score_margin),
                func.max(GameEvent.score_margin),
            )
            .where(GameEvent.game_id.in_(list(game_map)))
            .group_by(GameEvent.game_id)
        )
    ).all()
    if not rows:
        return ToolResult(
            status="incomplete_coverage",
            message="No play-by-play score-margin data is available for this ranking.",
            evidence=[tools.receipt(game) for game in games],
            scope=scope.model_dump(mode="json"),
        )
    ranked: list[tuple[int, Game, int, int]] = []
    for game_id, minimum_home, maximum_home in rows:
        game = game_map.get(int(game_id))
        if game is None:
            continue
        lowest = min(int(minimum_home), 0)
        highest = max(int(maximum_home), 0)
        if game.home_team_id == "NYK":
            low, high = lowest, highest
        else:
            low, high = -highest, -lowest
        ranked.append((high - low, game, low, high))
    ranked.sort(
        key=lambda item: (item[0], item[3], str(item[1].game_date), item[1].id), reverse=True
    )
    ranked_games = [game for _, game, _, _ in ranked]
    evidence = [tools.receipt(game) for game in ranked_games]
    claims = []
    for index, (span, game, low, high) in enumerate(ranked[:5], start=1):
        own, other = tools.score(game)
        claims.append(
            team_claim(
                tools,
                scope,
                population=ranked_games,
                metric="score_margin_range",
                value=span,
                unit="points",
                statement=(
                    f"Rank {index} for observed swing: {game.game_date} against "
                    f"{opponent(game)} spanned {span} points of Knicks margin "
                    f"({low} to {high}); final NYK {own}, {opponent(game)} {other}."
                ),
                games=[game],
                evidence=[tools.receipt(game)],
                limitations=[
                    "Observed play-by-play margin only; not a lead-change or comeback count.",
                    f"Swing ranking covers {len(ranked)} of {len(games)} games with "
                    "play-by-play margins.",
                ],
            )
        )
    if len(ranked) != len(games):
        claims.append(
            team_claim(
                tools,
                scope,
                population=ranked_games,
                metric="swing_coverage",
                value=len(ranked),
                unit="games",
                statement=(
                    f"Swing ranking covers {len(ranked)} of {len(games)} games with "
                    "play-by-play score margins."
                ),
                games=ranked_games,
                evidence=[tools.receipt(game) for game in ranked_games],
                limitations=[
                    "Games without play-by-play margins are not ranked and cannot be excluded "
                    "from a wider swing.",
                ],
            )
        )
    return ToolResult(
        status="ok" if len(ranked) == len(games) else "incomplete_coverage",
        message=(
            f"Ranked {len(ranked)} of {len(games)} games with play-by-play score margins; "
            "the range includes a zero anchor."
        ),
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
