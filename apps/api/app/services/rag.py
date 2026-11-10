"""Small retrieval layer for season documents."""

from __future__ import annotations

import json

from app.models.chunk_model import DocumentChunk
from app.models.document import Document
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.rag_ranking import _knicks_result
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def build_game_document_body(game: Game, events: list[GameEvent]) -> str:
    result = "won" if game.home_score > game.away_score else "lost"
    if game.away_team_id == "NYK":
        knicks_score = game.away_score
        opponent = game.home_team_id
        opponent_score = game.home_score
    else:
        knicks_score = game.home_score
        opponent = game.away_team_id
        opponent_score = game.away_score
    lines = [
        f"Knicks {result} {knicks_score}-{opponent_score} against {opponent} on {game.game_date}.",
        f"Season {game.season}; season type {game.season_type}; data status {game.data_status}.",
    ]
    if events:
        lines.append("Play-by-play highlights:")
        lines.extend(
            f"Q{event.period} {event.clock} {event.team_id or '-'}: {event.description}"
            for event in events[:40]
            if event.description
        )
    return "\n".join(lines)


async def upsert_game_documents(
    db: AsyncSession,
    game: Game,
    events: list[GameEvent],
    embedding_json: str | None = None,
) -> int:
    """Replace generated RAG docs/chunks for one game."""
    existing = (
        (
            await db.execute(
                select(Document).where(
                    Document.game_id == game.id,
                    Document.source_type.in_(("game_summary", "play_by_play")),
                )
            )
        )
        .scalars()
        .all()
    )
    for doc in existing:
        await db.delete(doc)
    await db.flush()

    body = build_game_document_body(game, events)
    doc_type = "play_by_play" if events else "game_summary"
    doc = Document(
        source_type=doc_type,
        title=f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
        body=body,
        game_id=game.id,
        team_id="NYK",
    )
    db.add(doc)
    await db.flush()

    metadata = {
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": game.home_team_id if game.away_team_id == "NYK" else game.away_team_id,
        "result": _knicks_result(game),
        "season_type": game.season_type,
        "doc_type": doc_type,
        "data_status": game.data_status,
        "source_name": game.source_name,
        "source_url": game.source_url,
    }
    db.add(
        DocumentChunk(
            document_id=doc.id,
            sequence=0,
            text=body,
            embedding_json=embedding_json,
            metadata_json=json.dumps(metadata),
        )
    )
    return 1
