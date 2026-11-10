"""Rag ranking."""

from __future__ import annotations

import json
import re

from app.models.game import Game
from app.services.possession_chunks import (
    PossessionChunk,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def _knicks_result(game: Game) -> str:
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    return "W" if knicks_score > opponent_score else "L"


def _bm25ish_score(query_tokens: set[str], text: str) -> float:
    text_tokens = _TOKEN_RE.findall(text.lower())
    if not text_tokens:
        return 0.0
    counts = {token: text_tokens.count(token) for token in query_tokens}
    return sum(count / (1.2 + count) for count in counts.values())


def lexical_rank_chunks(
    query: str,
    chunks: list[PossessionChunk],
) -> tuple[list[tuple[PossessionChunk, float]], list[tuple[PossessionChunk, float]]]:
    query_tokens = _tokens(query)
    lexical = [
        (chunk, _bm25ish_score(query_tokens, f"{chunk.text} {json.dumps(chunk.metadata)}"))
        for chunk in chunks
    ]
    lexical = [(chunk, score) for chunk, score in lexical if score > 0 or not query_tokens]
    lexical.sort(key=lambda item: (-item[1], item[0].chunk_id))

    player_rank = [
        (
            chunk,
            float(
                len(
                    query_tokens
                    & {
                        token
                        for name in chunk.metadata.get("player_names", [])
                        for token in _tokens(name)
                    }
                )
            ),
        )
        for chunk in chunks
    ]
    player_rank = [(chunk, score) for chunk, score in player_rank if score > 0]
    player_rank.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return lexical, player_rank
