"""Worker command-line tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings as get_api_settings
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.ingest_run import IngestRun
from app.services.rag_index import GAME_ORDER_CHOICES, build_rag_artifacts
from sqlalchemy import func, select

from worker_app.core.config import get_settings
from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import create_job
from worker_app.jobs.detect_runs import detect_game_features
from worker_app.jobs.ingest_game_detail import ingest_game_detail
from worker_app.jobs.ingest_games import ingest_games
from worker_app.jobs.seed_players_from_nba_api import seed_season_rosters_from_nba_api


async def _team_games(team: str, season: str) -> list[Game]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(Game)
                    .where(Game.season == season)
                    .where((Game.home_team_id == team) | (Game.away_team_id == team))
                    .order_by(Game.game_date, Game.id)
                )
            )
            .scalars()
            .all()
        )


async def _event_count(game_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            (
                await db.execute(
                    select(func.count(GameEvent.id)).where(GameEvent.game_id == game_id)
                )
            ).scalar_one()
        )


async def _mark_analysis_ready(game_id: int) -> None:
    async with AsyncSessionLocal() as db:
        game = await db.get(Game, game_id)
        if game:
            game.data_status = "analysis_ready"
            await db.commit()


async def _run_detect_features(game_id: int, season: str) -> dict[str, Any]:
    detect_job_id = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        await create_job(
            db,
            job_id=detect_job_id,
            job_type="cache_season_detect_features",
            payload={"game_id": game_id, "season": season},
            enqueued_by="cli",
        )
    result = await detect_game_features(job_id=detect_job_id, game_db_id=game_id)
    if result.get("events_processed", 0) <= 0:
        raise ValueError(f"Game {game_id} has no events to analyze")
    await _mark_analysis_ready(game_id)
    return result


async def _cache_season(
    team: str,
    season: str,
    include_playoffs: bool,
    *,
    demo_ready: bool = False,
    rag_out_dir: str = "rag-artifacts",
    reset_qdrant: bool = False,
) -> dict:
    if team != "NYK":
        raise ValueError("Only NYK season caching is supported for the public demo")
    settings = get_settings()
    api_settings = get_api_settings()
    if demo_ready and not settings.test_mode and settings.data_source != "nba_api":
        raise ValueError("Demo-ready caching requires NBA_DATA_SOURCE=nba_api")

    games_job_id = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        await create_job(
            db,
            job_id=games_job_id,
            job_type="cache_season_games",
            payload={
                "team": team,
                "season": season,
                "include_playoffs": include_playoffs,
            },
            enqueued_by="cli",
        )

    games_result = await ingest_games(
        job_id=games_job_id,
        season=season,
        include_playoffs=include_playoffs,
    )
    games = await _team_games(team, season)
    game_ids = [game.id for game in games]

    detail_results = []
    for game_id in game_ids:
        game = next((row for row in games if row.id == game_id), None)
        if demo_ready and game and game.data_status == "analysis_ready":
            detail_results.append(
                {
                    "game_id": game_id,
                    "nba_game_id": game.nba_game_id,
                    "skipped": "analysis_ready",
                }
            )
            continue
        if demo_ready and await _event_count(game_id) > 0:
            detail_results.append(
                {
                    "game_id": game_id,
                    "nba_game_id": game.nba_game_id if game else None,
                    "skipped": "events_already_cached",
                }
            )
            continue
        detail_job_id = uuid.uuid4().hex
        async with AsyncSessionLocal() as db:
            await create_job(
                db,
                job_id=detail_job_id,
                job_type="cache_season_game_detail",
                payload={"game_id": game_id, "season": season},
                enqueued_by="cli",
            )
        try:
            detail_results.append(
                await ingest_game_detail(job_id=detail_job_id, game_db_id=game_id)
            )
        except Exception as exc:  # noqa: BLE001
            detail_results.append({"game_id": game_id, "error": str(exc)})

    detect_results: list[dict[str, Any]] = []
    rag_result: dict[str, Any] | None = None
    if demo_ready:
        for game in await _team_games(team, season):
            try:
                if await _event_count(game.id) <= 0:
                    raise ValueError(f"Game {game.id} has no cached play-by-play events")
                detect_results.append(await _run_detect_features(game.id, season))
            except Exception as exc:  # noqa: BLE001
                detect_results.append(
                    {
                        "game_id": game.id,
                        "nba_game_id": game.nba_game_id,
                        "error": str(exc),
                    }
                )
        try:
            async with AsyncSessionLocal() as db:
                rag_result = await build_rag_artifacts(
                    db,
                    season=season,
                    out_dir=Path(rag_out_dir),
                    summary_model=api_settings.openrouter_summary_model,
                    game_limit=None,
                    game_order="date",
                    reset_qdrant=reset_qdrant,
                )
        except Exception as exc:  # noqa: BLE001
            rag_result = {"error": str(exc)}

    async with AsyncSessionLocal() as db:
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.season == season)
                    .where((Game.home_team_id == team) | (Game.away_team_id == team))
                )
            )
            .scalars()
            .all()
        )
        status_counts = {
            "summary_only": sum(1 for g in games if g.data_status == "summary_only"),
            "events_ready": sum(1 for g in games if g.data_status == "events_ready"),
            "analysis_ready": sum(1 for g in games if g.data_status == "analysis_ready"),
        }
        failed_games = [row for row in [*detail_results, *detect_results] if row.get("error")]
        rag_selected_games = (
            int(rag_result.get("selected_game_count", 0)) if isinstance(rag_result, dict) else 0
        )
        rag_chunks = (
            int(rag_result.get("possession_chunk_count", 0)) if isinstance(rag_result, dict) else 0
        )
        ready = (
            demo_ready
            and len(games) > 0
            and not failed_games
            and status_counts["analysis_ready"] == len(games)
            and rag_result is not None
            and "error" not in rag_result
            and rag_selected_games == len(games)
            and rag_chunks > 0
        )
        summary = {
            "team": team,
            "season": season,
            "include_playoffs": include_playoffs,
            "demo_ready_requested": demo_ready,
            "ready": ready if demo_ready else None,
            "games_result": games_result,
            "total_games": len(games),
            "summary_only": status_counts["summary_only"],
            "events_ready": status_counts["events_ready"],
            "analysis_ready": status_counts["analysis_ready"],
            "detail_results": detail_results,
            "detect_results": detect_results,
            "failed_games": failed_games,
            "rag_artifacts_built": bool(rag_result is not None and "error" not in rag_result),
            "rag_result": rag_result,
        }
        db.add(
            IngestRun(
                job_id=games_job_id,
                source_name="season_cache_cli",
                team_id=team,
                season=season,
                include_playoffs=1 if include_playoffs else 0,
                summary_json=json.dumps(summary, default=str),
            )
        )
        await db.commit()
    return summary


def _cache_season_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cache Knicks season data")
    parser.add_argument("--team", default="NYK")
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--include-playoffs", action="store_true")
    parser.add_argument(
        "--demo-ready",
        action="store_true",
        help=(
            "Build a strict demo cache: backfill missing data, run analysis, "
            "rebuild RAG artifacts, and fail unless every cached game is ready."
        ),
    )
    parser.add_argument("--rag-out-dir", default="rag-artifacts")
    parser.add_argument("--reset-qdrant", action="store_true")
    return parser


def cache_season_main() -> None:
    parser = _cache_season_parser()
    args = parser.parse_args()
    result = asyncio.run(
        _cache_season(
            args.team,
            args.season,
            args.include_playoffs,
            demo_ready=args.demo_ready,
            rag_out_dir=args.rag_out_dir,
            reset_qdrant=args.reset_qdrant,
        )
    )
    print(json.dumps(result, indent=2, default=str))
    if args.demo_ready and not result.get("ready"):
        sys.exit(1)


async def _cache_rosters(season: str) -> dict:
    job_id = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        await create_job(
            db,
            job_id=job_id,
            job_type="cache_season_rosters",
            payload={"season": season},
            enqueued_by="cli",
        )
    return await seed_season_rosters_from_nba_api(job_id=job_id, season=season)


def cache_rosters_main() -> None:
    parser = argparse.ArgumentParser(description="Cache historical season rosters")
    parser.add_argument("--season", default="2025-26")
    args = parser.parse_args()
    result = asyncio.run(_cache_rosters(args.season))
    print(json.dumps(result, indent=2, default=str))


async def _build_rag_index(
    season: str,
    out_dir: str,
    game_limit: int | None,
    game_order: str,
    reset_qdrant: bool,
    data_version: str | None = None,
) -> dict:
    async with AsyncSessionLocal() as db:
        return await build_rag_artifacts(
            db,
            season=season,
            out_dir=Path(out_dir),
            summary_model=get_api_settings().openrouter_summary_model,
            game_limit=game_limit,
            game_order=game_order,
            reset_qdrant=reset_qdrant,
            data_version=data_version,
        )


def _build_rag_index_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build derived RAG artifacts from the current cached DB only"
    )
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--out-dir", default="rag-artifacts")
    parser.add_argument(
        "--data-version",
        help="Validated release version; builds a physical collection then switches the alias.",
    )
    parser.add_argument(
        "--game-limit",
        type=int,
        default=None,
        help="Limit indexing to N selected games. Omit to index all cached games.",
    )
    parser.add_argument(
        "--game-order",
        choices=GAME_ORDER_CHOICES,
        default="date",
        help="Select games by chronological date order or most recent first.",
    )
    parser.add_argument(
        "--reset-qdrant",
        action="store_true",
        help="Recreate the configured possessions collection before upserting.",
    )
    return parser


def build_rag_index_main() -> None:
    parser = _build_rag_index_parser()
    args = parser.parse_args()
    result = asyncio.run(
        _build_rag_index(
            args.season,
            args.out_dir,
            args.game_limit,
            args.game_order,
            args.reset_qdrant,
            args.data_version,
        )
    )
    print(json.dumps(result, indent=2, default=str))
