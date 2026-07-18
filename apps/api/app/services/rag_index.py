"""Build derived RAG artifacts from cached DB rows only."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.report import Report
from app.services.embeddings import embed_texts
from app.services.possession_chunks import build_possession_chunks
from app.services.qdrant_client import (
    ensure_collections,
    recreate_collection,
    switch_aliases,
    upsert_points,
    versioned_collection,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

QDRANT_INDEX_BATCH_SIZE = 512
GAME_ORDER_DATE = "date"
GAME_ORDER_RECENT = "recent"
GAME_ORDER_CHOICES = (GAME_ORDER_DATE, GAME_ORDER_RECENT)

logger = logging.getLogger(__name__)


def _semantic_summary(text: str, *, max_chars: int = 360) -> str:
    """Deterministic local summary fallback for possession payloads."""
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[:max_chars]


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


def _select_games(
    games: list[Game],
    *,
    game_limit: int | None,
    game_order: str,
) -> list[Game]:
    if game_order not in GAME_ORDER_CHOICES:
        raise ValueError(f"Unsupported game_order: {game_order}")
    reverse = game_order == GAME_ORDER_RECENT
    selected = sorted(games, key=lambda game: (game.game_date, game.id), reverse=reverse)
    if game_limit is not None:
        selected = selected[:game_limit]
    return selected


async def build_rag_artifacts(
    db: AsyncSession,
    *,
    season: str,
    out_dir: Path,
    summary_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free",
    game_limit: int | None = None,
    game_order: str = GAME_ORDER_DATE,
    reset_qdrant: bool = False,
    data_version: str | None = None,
) -> dict[str, Any]:
    """Write derived possession chunks and table exports without mutating source data."""
    started_at = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    games_stmt = (
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date)
    )
    if data_version:
        games_stmt = games_stmt.join(DatasetRelease, Game.release_id == DatasetRelease.id).where(
            DatasetRelease.version == data_version,
            DatasetRelease.validation_passed.is_(True),
        )
    all_games = list((await db.execute(games_stmt)).scalars().all())
    games = _select_games(all_games, game_limit=game_limit, game_order=game_order)
    game_ids = [game.id for game in games]
    logger.info(
        "rag_index_games_selected",
        extra={
            "season": season,
            "available_games": len(all_games),
            "selected_games": len(games),
            "game_limit": game_limit,
            "game_order": game_order,
        },
    )
    events = list(
        (
            await db.execute(
                select(GameEvent)
                .options(selectinload(GameEvent.player))
                .where(GameEvent.game_id.in_(game_ids))
                .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
            )
        )
        .scalars()
        .all()
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
            for chunk in build_possession_chunks(
                game,
                events_by_game.get(game.id, []),
                contextual_event_windows=getattr(
                    get_settings(),
                    "rag_contextual_event_windows_enabled",
                    False,
                ),
            ):
                # Index construction is offline, deterministic, and provider-free.
                # OpenRouter is reserved for optional runtime phrasing only.
                summary = _semantic_summary(chunk.text)
                record = {
                    "id": chunk.chunk_id,
                    "text": chunk.text,
                    "semantic_summary": summary,
                    "summary_model": "deterministic-extractive-v1",
                    "payload": {**chunk.metadata, "raw_rows": chunk.rows},
                }
                qdrant_record = {
                    "id": chunk.chunk_id,
                    "payload": {
                        **chunk.metadata,
                        "data_version": data_version,
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
        import polars as pl  # type: ignore[import-not-found]

        parquet_path = out_dir / "games_table.parquet"
        pl.DataFrame(game_rows).write_parquet(parquet_path)
        parquet_export = str(parquet_path)
    except ImportError:
        parquet_export = None

    qdrant_upserted = 0
    qdrant_reset = False
    supporting_counts: dict[str, int] = {}
    settings = get_settings()
    possession_collection = (
        versioned_collection(settings.rag_qdrant_possessions_collection, data_version)
        if data_version
        else settings.rag_qdrant_possessions_collection
    )
    if settings.rag_qdrant_enabled and (reset_qdrant or data_version):
        recreate_collection(possession_collection)
        qdrant_reset = True
    elif settings.rag_qdrant_enabled and possession_records:
        ensure_collections()
    if settings.rag_qdrant_enabled and possession_records:
        for batch in _iter_batches(possession_records, QDRANT_INDEX_BATCH_SIZE):
            documents = [_embedding_text(record) for record in batch]
            if getattr(settings, "rag_qdrant_cloud_inference", False):
                qdrant_upserted += upsert_points(
                    possession_collection,
                    batch,
                    documents=documents,
                )
            else:
                qdrant_upserted += upsert_points(
                    possession_collection,
                    # Writes target an immutable physical collection when a release
                    # version is supplied; the stable alias moves only after validation.
                    batch,
                    embed_texts(documents),
                )
            logger.info(
                "rag_index_qdrant_batch_upserted",
                extra={
                    "collection": possession_collection,
                    "batch_size": len(batch),
                    "qdrant_upserted": qdrant_upserted,
                },
            )
        if qdrant_upserted != len(possession_records):
            raise RuntimeError("Qdrant indexed point count did not match release records")
        if data_version:
            supporting_counts, supporting_collections = await _build_release_supporting_collections(
                db, games, data_version
            )
            switch_aliases(
                {
                    settings.rag_qdrant_possessions_collection: possession_collection,
                    **supporting_collections,
                }
            )
        else:
            supporting_counts = {}

    manifest = {
        "season": season,
        "source": "cached_db_only",
        "games": len(games),
        "available_games": len(all_games),
        "selected_game_count": len(games),
        "selected_games": [
            {
                "game_id": game.id,
                "date": str(game.game_date),
                "home_team_id": game.home_team_id,
                "away_team_id": game.away_team_id,
                "season_type": game.season_type,
                "data_status": game.data_status,
            }
            for game in games
        ],
        "game_limit": game_limit,
        "game_order": game_order,
        "events": len(events),
        "possession_chunks": chunk_count,
        "possession_chunk_count": chunk_count,
        "payload_path": str(payload_path),
        "chunks_path": str(chunks_path),
        "table_export": str(table_export),
        "parquet_export": parquet_export,
        "summary_model": "deterministic-extractive-v1",
        "qdrant_enabled": settings.rag_qdrant_enabled,
        "qdrant_reset_requested": reset_qdrant,
        "qdrant_reset": qdrant_reset,
        "qdrant_upserted": qdrant_upserted,
        "qdrant_supporting_counts": supporting_counts,
        "data_version": data_version,
        "qdrant_collection": possession_collection,
        "qdrant_batch_size": QDRANT_INDEX_BATCH_SIZE,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    logger.info(
        "rag_index_complete",
        extra={
            "selected_games": manifest["selected_game_count"],
            "possession_chunks": chunk_count,
            "qdrant_reset": qdrant_reset,
            "qdrant_upserted": qdrant_upserted,
            "elapsed_seconds": manifest["elapsed_seconds"],
        },
    )
    return manifest


async def _build_release_supporting_collections(
    db: AsyncSession,
    games: list[Game],
    data_version: str,
) -> tuple[dict[str, int], dict[str, str]]:
    """Build summaries, box facts, and reviewed reports before alias promotion."""
    settings = get_settings()
    game_ids = [game.id for game in games]
    games_by_id = {game.id: game for game in games}
    team_stats = list(
        (await db.execute(select(TeamGameStat).where(TeamGameStat.game_id.in_(game_ids))))
        .scalars()
        .all()
    )
    player_stats = list(
        (await db.execute(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(game_ids))))
        .scalars()
        .all()
    )
    reports = list(
        (
            await db.execute(
                select(Report).where(Report.game_id.in_(game_ids), Report.reviewed.is_(True))
            )
        )
        .scalars()
        .all()
    )
    game_records = [
        {
            "id": f"game:{game.id}:summary",
            "payload": {
                "game_id": game.id,
                "data_version": data_version,
                "date": str(game.game_date),
                "season": game.season,
                "team_ids": [game.home_team_id, game.away_team_id],
                "semantic_summary": (
                    f"{game.away_team_id} {game.away_score} at "
                    f"{game.home_team_id} {game.home_score} on {game.game_date}"
                ),
            },
        }
        for game in games
    ]
    box_records = [
        {
            "id": f"team-box:{row.game_id}:{row.team_id}",
            "payload": {
                "game_id": row.game_id,
                "data_version": data_version,
                "date": str(games_by_id[row.game_id].game_date),
                "season": games_by_id[row.game_id].season,
                "season_type": games_by_id[row.game_id].season_type,
                "team_ids": [row.team_id],
                "semantic_summary": (
                    f"{row.team_id} team box: {row.points} points, "
                    f"{row.rebounds} rebounds, {row.assists} assists, "
                    f"{row.turnovers} turnovers"
                ),
            },
        }
        for row in team_stats
    ]
    box_records.extend(
        {
            "id": f"player-box:{row.game_id}:{row.player_id}",
            "payload": {
                "game_id": row.game_id,
                "data_version": data_version,
                "date": str(games_by_id[row.game_id].game_date),
                "season": games_by_id[row.game_id].season,
                "season_type": games_by_id[row.game_id].season_type,
                "team_ids": [row.team_id],
                "player_ids": [row.player_id],
                "semantic_summary": (
                    f"Player {row.player_id}: {row.points} points, "
                    f"{row.rebounds} rebounds, {row.assists} assists, "
                    f"{row.turnovers} turnovers"
                ),
            },
        }
        for row in player_stats
    )
    report_records = [
        {
            "id": f"report:{row.id}",
            "payload": {
                "game_id": row.game_id,
                "data_version": data_version,
                "date": str(games_by_id[row.game_id].game_date),
                "season": games_by_id[row.game_id].season,
                "season_type": games_by_id[row.game_id].season_type,
                "team_ids": [
                    games_by_id[row.game_id].home_team_id,
                    games_by_id[row.game_id].away_team_id,
                ],
                "semantic_summary": f"{row.title}. {row.summary}",
            },
        }
        for row in reports
    ]
    collections = {
        settings.rag_qdrant_games_collection: game_records,
        settings.rag_qdrant_box_scores_collection: box_records,
        settings.rag_qdrant_reports_collection: report_records,
    }
    counts: dict[str, int] = {}
    physical_names: dict[str, str] = {}
    for alias, records in collections.items():
        physical = versioned_collection(alias, data_version)
        physical_names[alias] = physical
        recreate_collection(physical)
        inserted = 0
        for batch in _iter_batches(records, QDRANT_INDEX_BATCH_SIZE):
            documents = [str(record["payload"]["semantic_summary"]) for record in batch]
            if settings.rag_qdrant_cloud_inference:
                inserted += upsert_points(physical, batch, documents=documents)
            else:
                inserted += upsert_points(physical, batch, embed_texts(documents))
        if inserted != len(records) or not records:
            raise RuntimeError(f"Qdrant {alias} validation failed")
        counts[alias] = inserted
    return counts, physical_names
