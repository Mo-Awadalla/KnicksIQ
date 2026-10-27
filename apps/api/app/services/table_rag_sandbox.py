"""Table rag sandbox."""

from __future__ import annotations

import ast
from types import MappingProxyType
from typing import Any

from app.models.game import Game
from app.services.table_rag_types import _table_row

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


def validate_table_expression(expression: str) -> ast.Expression:
    """Validate a tiny aggregate-expression AST before execution."""
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise TableRagSandboxError("Invalid table expression syntax.") from exc

    for node in ast.walk(parsed):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise TableRagSandboxError(f"Unsupported table expression node: {type(node).__name__}.")
        if isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                raise TableRagSandboxError(f"Blocked table expression name: {node.id}.")
            if node.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(f"Unknown table expression name: {node.id}.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise TableRagSandboxError("Only direct aggregate helper calls are allowed.")
            if node.func.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(f"Unsupported aggregate helper: {node.func.id}.")
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
