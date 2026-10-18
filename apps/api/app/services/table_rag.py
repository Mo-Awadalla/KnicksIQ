"""Read-only table RAG over available game rows."""

from __future__ import annotations

import asyncio
import re

from app.services.table_rag_box_scores import _answer_box_score_question, _answer_team_comparison
from app.services.table_rag_games import _answer_from_games, _season_games
from app.services.table_rag_swings import _answer_swing_question
from app.services.table_rag_templates import template_intent
from app.services.table_rag_types import TableRagResult, _game_evidence
from app.services.team_scope import comparison_groups, scope_games
from sqlalchemy.ext.asyncio import AsyncSession

TABLE_RAG_TIMEOUT_SECONDS = 1.5


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
    all_games = await asyncio.wait_for(_season_games(db, season), timeout=timeout_seconds)
    games = scope_games(question, all_games, window=False)
    q = question.lower()
    if "back-to-back" in q or "back to back" in q:
        return TableRagResult(
            answer=(
                "Do you mean wins in the second game of a back-to-back, "
                "or back-to-back sets where the Knicks won both games?"
            ),
            evidence=[],
            warnings=[],
        )
    if "close games" in q and "blowout" in q:
        return TableRagResult(
            answer="What final-margin cutoffs should define close games and blowouts?",
            evidence=[],
            warnings=[],
        )
    if "stronger" in q and "offense" in q and "defense" in q:
        return TableRagResult(
            answer=(
                "Which measure should I compare: points scored versus points allowed, "
                "or the changes in those numbers over a particular game window?"
            ),
            evidence=[],
            warnings=[],
        )
    if "compare" in q and re.search(r"\b(?:two|2)\b", q) and len(games) != 2:
        dates = ", ".join(str(game.game_date) for game in games)
        return TableRagResult(
            answer=f"I found {len(games)} matching games: {dates}. Which two should I compare?",
            evidence=[_game_evidence(game) for game in games],
            warnings=[],
        )
    groups = comparison_groups(question, games)
    if groups:
        return await _answer_team_comparison(db, question, groups)
    games = scope_games(question, all_games)
    if template_intent(question) in {
        "points_allowed",
        "average_margin",
        "highest_scoring",
        "lowest_scoring",
        "game_count",
        "score_threshold",
    }:
        return _answer_from_games(question, season, games)
    swing_answer = await asyncio.wait_for(
        _answer_swing_question(db, question, season, games),
        timeout=timeout_seconds,
    )
    if swing_answer is not None:
        return swing_answer
    box_score_answer = await asyncio.wait_for(
        _answer_box_score_question(db, question, season, games),
        timeout=timeout_seconds,
    )
    if box_score_answer is not None:
        return box_score_answer
    return await asyncio.wait_for(
        asyncio.to_thread(_answer_from_games, question, season, games),
        timeout=timeout_seconds,
    )
