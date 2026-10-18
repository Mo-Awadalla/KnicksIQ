"""Table rag types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.game import Game


@dataclass(frozen=True)
class TableRagResult:
    answer: str
    evidence: list[dict[str, Any]]
    warnings: list[str]


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
