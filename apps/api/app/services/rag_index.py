"""Build derived RAG artifacts from cached DB rows only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.embeddings import embed_texts
from app.services.possession_chunks import build_possession_chunks
from app.services.qdrant_client import ensure_collections, upsert_points
from app.services.report_llm import OpenAICompatibleLLMAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

QDRANT_INDEX_BATCH_SIZE = 512


def _semantic_summary(text: str, *, max_chars: int = 360) -> str:
    """Deterministic local summary fallback for possession payloads."""
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[:max_chars]


async def _summarize_possession(text: str, *, summary_model: str) -> str:
    settings = get_settings()
    if not settings.openrouter_api_key:
        return _semantic_summary(text)
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
        model=summary_model,
        timeout_seconds=settings.ai_request_timeout_seconds,
        response_format_json=False,
    )
    system = (
        "Summarize this NBA possession window in one short factual sentence. "
        "Use only the supplied rows."
    )
    try:
        return await adapter.generate(system=system, user=text)
    except Exception:  # noqa: B110
        return _semantic_summary(text)


def _embedding_text(record: dict[str, Any]) -> str:
    """Compact text used for dense retrieval while payload keeps full evidence."""
    payload = record["payload"]
    players = ", ".join(payload.get("player_names") or [])
    teams = ", ".join(payload.get("team_ids") or [])
    period_window = (
        f"Q{payload.get('start_period')} {payload.get('start_clock')} "
        f"to Q{payload.get('end_period')} {payload.get('end_clock')}"
    )
    parts = [
        str(payload.get("semantic_summary") or ""),
        f"Date: {payload.get('date')}; season: {payload.get('season')}; "
        f"type: {payload.get('season_type')}",
        f"Teams: {teams}" if teams else "",
        f"Players: {players}" if players else "",
        period_window,
        str(payload.get("text") or "")[:220],
    ]
    return "\n".join(part for part in parts if part)


def _iter_batches(items: list[dict[str, Any]], batch_size: int):
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


async def build_rag_artifacts(
    db: AsyncSession,
    *,
    season: str,
    out_dir: Path,
    summary_model: str = "poolside/laguna-xs-2.1:free",
) -> dict[str, Any]:
    """Write derived possession chunks and table exports without mutating source data."""
    out_dir.mkdir(parents=True, exist_ok=True)
    games = list(
        (
            await db.execute(
                select(Game)
                .where(Game.season == season)
                .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
                .order_by(Game.game_date)
            )
        ).scalars().all()
    )
    game_ids = [game.id for game in games]
    events = list(
        (
            await db.execute(
                select(GameEvent)
                .options(selectinload(GameEvent.player))
                .where(GameEvent.game_id.in_(game_ids))
                .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
            )
        ).scalars().all()
    )
    events_by_game: dict[int, list[GameEvent]] = {}
    for event in events:
        events_by_game.setdefault(event.game_id, []).append(event)

    payload_path = out_dir / "qdrant_payloads.jsonl"
    chunks_path = out_dir / "possession_chunks.jsonl"
    game_rows = []
    possession_records: list[dict[str, Any]] = []
    chunk_count = 0
    with payload_path.open("w") as payload_file, chunks_path.open("w") as chunks_file:
        for game in games:
            game_rows.append(
                {
                    "game_id": game.id,
                    "date": str(game.game_date),
                    "season": game.season,
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "season_type": game.season_type,
                    "data_status": game.data_status,
                }
            )
            for chunk in build_possession_chunks(game, events_by_game.get(game.id, [])):
                summary = await _summarize_possession(
                    chunk.text, summary_model=summary_model
                )
                record = {
                    "id": chunk.chunk_id,
                    "text": chunk.text,
                    "semantic_summary": summary,
                    "summary_model": summary_model,
                    "payload": {**chunk.metadata, "raw_rows": chunk.rows},
                }
                qdrant_record = {
                    "id": chunk.chunk_id,
                    "payload": {
                        **chunk.metadata,
                        "chunk_id": chunk.chunk_id,
                        "text": chunk.text,
                        "semantic_summary": summary,
                        "raw_rows": chunk.rows,
                    },
                }
                possession_records.append(qdrant_record)
                chunks_file.write(json.dumps(record, default=str) + "\n")
                payload_file.write(json.dumps(qdrant_record, default=str) + "\n")
                chunk_count += 1

    table_export = out_dir / "games_table.json"
    table_export.write_text(json.dumps(game_rows, indent=2, default=str))
    parquet_export: str | None = None
    try:
        import polars as pl

        parquet_path = out_dir / "games_table.parquet"
        pl.DataFrame(game_rows).write_parquet(parquet_path)
        parquet_export = str(parquet_path)
    except ImportError:
        parquet_export = None

    qdrant_upserted = 0
    settings = get_settings()
    if settings.rag_qdrant_enabled and possession_records:
        ensure_collections()
        for batch in _iter_batches(possession_records, QDRANT_INDEX_BATCH_SIZE):
            embeddings = embed_texts([_embedding_text(record) for record in batch])
            qdrant_upserted += upsert_points(
                settings.rag_qdrant_possessions_collection,
                batch,
                embeddings,
            )

    manifest = {
        "season": season,
        "source": "cached_db_only",
        "games": len(games),
        "events": len(events),
        "possession_chunks": chunk_count,
        "payload_path": str(payload_path),
        "chunks_path": str(chunks_path),
        "table_export": str(table_export),
        "parquet_export": parquet_export,
        "summary_model": summary_model,
        "qdrant_enabled": settings.rag_qdrant_enabled,
        "qdrant_upserted": qdrant_upserted,
        "qdrant_collection": settings.rag_qdrant_possessions_collection,
        "qdrant_batch_size": QDRANT_INDEX_BATCH_SIZE,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest
