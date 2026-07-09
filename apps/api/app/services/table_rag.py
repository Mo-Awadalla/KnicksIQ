"""Read-only table RAG over cached game rows."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.models.game import Game
from app.services.table_rag_templates import polars_summary, template_intent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

TABLE_RAG_TIMEOUT_SECONDS = 1.5
_BLOCKED_NAMES = {
    "__import__",
    "eval",
    "exec",
    "open",
    "os",
    "pathlib",
    "shutil",
    "subprocess",
    "sys",
}
_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.keyword,
)
_ALLOWED_TABLE_FUNCTIONS = {
    "average_points_against",
    "average_points_for",
    "count_games",
    "largest_win_margin",
    "losses",
    "sum_points_against",
    "sum_points_for",
    "wins",
}
_DATA_STATUS_RANK = {"summary_only": 0, "events_ready": 1, "analysis_ready": 2}


@dataclass(frozen=True)
class TableRagResult:
    answer: str
    evidence: list[dict[str, Any]]
    warnings: list[str]


class TableRagSandboxError(ValueError):
    """Raised when a table expression is not safe to execute."""


class ReadOnlyTable:
    """Immutable game rows exposed to TableRAG math helpers."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = tuple(MappingProxyType(dict(row)) for row in rows)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


def _knicks_scores(game: Game) -> tuple[int, int, str]:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    return knicks_score, opponent_score, opponent


def _game_evidence(game: Game) -> dict[str, Any]:
    knicks_score, opponent_score, opponent = _knicks_scores(game)
    return {
        "type": "game",
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": opponent,
        "score": {"NYK": knicks_score, opponent: opponent_score},
        "season_type": game.season_type,
        "data_status": game.data_status,
        "source_name": game.source_name,
        "source_url": game.source_url,
    }


def _table_row(game: Game) -> dict[str, Any]:
    knicks_score, opponent_score, opponent = _knicks_scores(game)
    return {
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": opponent,
        "knicks_score": knicks_score,
        "opponent_score": opponent_score,
        "knicks_win": knicks_score > opponent_score,
        "season_type": game.season_type,
        "data_status": game.data_status,
    }


def validate_table_expression(expression: str) -> ast.Expression:
    """Validate a tiny aggregate-expression AST before execution."""
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise TableRagSandboxError("Invalid table expression syntax.") from exc

    for node in ast.walk(parsed):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise TableRagSandboxError(
                f"Unsupported table expression node: {type(node).__name__}."
            )
        if isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                raise TableRagSandboxError(f"Blocked table expression name: {node.id}.")
            if node.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(f"Unknown table expression name: {node.id}.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise TableRagSandboxError("Only direct aggregate helper calls are allowed.")
            if node.func.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(
                    f"Unsupported aggregate helper: {node.func.id}."
                )
            if node.args or node.keywords:
                raise TableRagSandboxError("Aggregate helpers do not accept arguments.")
    return parsed


def evaluate_table_expression(expression: str, games: list[Game]) -> int | float:
    """Evaluate allowlisted aggregate math over immutable cached rows."""
    parsed = validate_table_expression(expression)
    table = ReadOnlyTable([_table_row(game) for game in games])

    def count_games() -> int:
        return len(table)

    def wins() -> int:
        return sum(1 for row in table if row["knicks_win"])

    def losses() -> int:
        return len(table) - wins()

    def largest_win_margin() -> int:
        margins = [
            int(row["knicks_score"]) - int(row["opponent_score"])
            for row in table
            if row["knicks_win"]
        ]
        return max(margins) if margins else 0

    def sum_points_for() -> int:
        return sum(int(row["knicks_score"]) for row in table)

    def sum_points_against() -> int:
        return sum(int(row["opponent_score"]) for row in table)

    def average_points_for() -> float:
        return sum_points_for() / len(table) if table else 0.0

    def average_points_against() -> float:
        return sum_points_against() / len(table) if table else 0.0

    safe_locals = {
        "average_points_against": average_points_against,
        "average_points_for": average_points_for,
        "count_games": count_games,
        "largest_win_margin": largest_win_margin,
        "losses": losses,
        "sum_points_against": sum_points_against,
        "sum_points_for": sum_points_for,
        "wins": wins,
    }
    return eval(  # noqa: S307
        compile(parsed, "<table_rag_expression>", "eval"),
        {"__builtins__": {}},
        safe_locals,
    )


async def _season_games(db: AsyncSession, season: str) -> list[Game]:
    rows = (
        await db.execute(
            select(Game)
            .where(Game.season == season)
            .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
            .order_by(Game.game_date)
        )
    ).scalars().all()
    return _dedupe_games(list(rows))


def _dedupe_games(games: list[Game]) -> list[Game]:
    """Collapse duplicate cached rows for the same final game.

    Some local/dev caches can contain a seed summary row and a later source row
    for the same date, teams, and final score. TableRAG should count that once
    and prefer the row with richer event data.
    """
    selected: dict[tuple, Game] = {}
    for game in games:
        key = (
            game.game_date,
            game.home_team_id,
            game.away_team_id,
            game.home_score,
            game.away_score,
        )
        existing = selected.get(key)
        if existing is None:
            selected[key] = game
            continue
        current_rank = _DATA_STATUS_RANK.get(game.data_status, 0)
        existing_rank = _DATA_STATUS_RANK.get(existing.data_status, 0)
        if (current_rank, game.id) > (existing_rank, existing.id):
            selected[key] = game
    return sorted(selected.values(), key=lambda game: (game.game_date, game.id))


def _answer_from_games(question: str, season: str, games: list[Game]) -> TableRagResult:
    q = question.lower()
    warnings: list[str] = []
    if not games:
        return TableRagResult(
            answer=f"No cached Knicks games were found for {season}.",
            evidence=[],
            warnings=[f"No cached games for season {season}."],
        )

    summary_only = sum(1 for game in games if game.data_status == "summary_only")
    if summary_only:
        warnings.append(
            f"{summary_only} cached game(s) are summary-only; aggregate score math is available, "
            "but event-level detail is incomplete."
        )

    evidence = [_game_evidence(game) for game in games]
    summary = polars_summary([_table_row(game) for game in games])
    wins = int(summary["wins"]) if summary else int(evaluate_table_expression("wins()", games))
    losses = (
        int(summary["losses"])
        if summary
        else int(evaluate_table_expression("losses()", games))
    )
    points_for = (
        int(summary["points_for"])
        if summary
        else int(evaluate_table_expression("sum_points_for()", games))
    )
    points_against = (
        int(summary["points_against"])
        if summary
        else int(evaluate_table_expression("sum_points_against()", games))
    )
    intent = template_intent(question)

    if intent == "longest_losing_streak":
        longest_streak: list[Game] = []
        current_streak: list[Game] = []
        for game in games:
            knicks_score, opponent_score, _ = _knicks_scores(game)
            if knicks_score < opponent_score:
                current_streak.append(game)
                if len(current_streak) > len(longest_streak):
                    longest_streak = list(current_streak)
            else:
                current_streak = []
        if not longest_streak:
            answer = f"In cached {season} Knicks games, NYK has no losing streak."
            evidence = []
        else:
            streak_evidence = [_game_evidence(game) for game in longest_streak]
            evidence = [
                *streak_evidence,
                *[
                    _game_evidence(game)
                    for game in games
                    if game.id not in {item.id for item in longest_streak}
                ],
            ]
            start = streak_evidence[0]
            end = streak_evidence[-1]
            date_text = (
                start["date"]
                if start["date"] == end["date"]
                else f"{start['date']} through {end['date']}"
            )
            answer = (
                f"The Knicks' longest cached {season} losing streak is "
                f"{len(longest_streak)} game(s), from {date_text}."
            )
    elif intent == "largest_loss_margin":
        knicks_losses = [
            (game, *_knicks_scores(game))
            for game in games
            if _knicks_scores(game)[0] < _knicks_scores(game)[1]
        ]
        if not knicks_losses:
            answer = f"In cached {season} Knicks games, NYK has no losses to rank."
        else:
            game, knicks_score, opponent_score, opponent = max(
                knicks_losses,
                key=lambda item: (item[2] - item[1], item[2], str(item[0].game_date)),
            )
            evidence = [
                _game_evidence(game),
                *[
                    _game_evidence(other_game)
                    for other_game in games
                    if other_game.id != game.id
                ],
            ]
            margin = opponent_score - knicks_score
            answer = (
                f"The biggest cached {season} Knicks loss was {game.game_date} "
                f"against {opponent}: NYK lost {knicks_score}-{opponent_score} "
                f"by {margin}."
            )
    elif intent == "largest_win_margin":
        knicks_wins = [
            (game, *_knicks_scores(game))
            for game in games
            if _knicks_scores(game)[0] > _knicks_scores(game)[1]
        ]
        if not knicks_wins:
            answer = f"In cached {season} Knicks games, NYK has no wins to rank."
        else:
            game, knicks_score, opponent_score, opponent = max(
                knicks_wins,
                key=lambda item: (item[1] - item[2], item[1], str(item[0].game_date)),
            )
            evidence = [
                _game_evidence(game),
                *[_game_evidence(other_game) for other_game in games if other_game.id != game.id],
            ]
            margin = int(evaluate_table_expression("largest_win_margin()", games))
            if "why did you pick" in q or "why those" in q or "why that" in q:
                answer = (
                    f"I picked {game.game_date} against {opponent} because this route "
                    f"ranks cached Knicks wins by final margin. NYK won "
                    f"{knicks_score}-{opponent_score}, a {margin}-point margin, which is "
                    f"the largest Knicks win margin in the cached {season} games."
                )
            else:
                answer = (
                    f"The Knicks' best cached {season} game by win margin was "
                    f"{game.game_date} against {opponent}: NYK won "
                    f"{knicks_score}-{opponent_score} by {margin}."
                )
    elif intent == "record":
        answer = f"In cached {season} Knicks games, NYK is {wins}-{losses}."
    elif intent == "points_average":
        avg_for = (
            float(summary["avg_for"])
            if summary
            else float(evaluate_table_expression("average_points_for()", games))
        )
        avg_against = (
            float(summary["avg_against"])
            if summary
            else float(evaluate_table_expression("average_points_against()", games))
        )
        answer = (
            f"Across {len(games)} cached {season} Knicks game(s), NYK averaged "
            f"{avg_for:.1f} points "
            f"and allowed {avg_against:.1f}."
        )
    elif intent == "points_total":
        answer = (
            f"Across {len(games)} cached {season} Knicks game(s), NYK scored "
            f"{points_for} total points and allowed {points_against}."
        )
    else:
        answer = (
            f"Cached table summary for {season}: {len(games)} game(s), "
            f"{wins}-{losses}, {points_for} points for, {points_against} against."
        )
    return TableRagResult(answer=answer, evidence=evidence, warnings=warnings)


async def answer_table_question(
    db: AsyncSession,
    question: str,
    *,
    season: str,
    timeout_seconds: float = TABLE_RAG_TIMEOUT_SECONDS,
) -> TableRagResult:
    """Answer aggregate questions from ORM-loaded rows only.

    The function does not evaluate user code, import runtime modules from user
    input, open files, make network calls, or mutate source basketball tables.
    """
    games = await asyncio.wait_for(_season_games(db, season), timeout=timeout_seconds)
    return await asyncio.wait_for(
        asyncio.to_thread(_answer_from_games, question, season, games),
        timeout=timeout_seconds,
    )
