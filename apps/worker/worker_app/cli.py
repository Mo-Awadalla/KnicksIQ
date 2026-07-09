"""Worker command-line tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.models.game import Game
from app.models.ingest_run import IngestRun
from app.services.rag_index import build_rag_artifacts
from sqlalchemy import select

from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import create_job
from worker_app.jobs.ingest_game_detail import ingest_game_detail
from worker_app.jobs.ingest_games import ingest_games
from worker_app.jobs.seed_players_from_nba_api import seed_season_rosters_from_nba_api


async def _cache_season(team: str, season: str, include_playoffs: bool) -> dict:
    if team != "NYK":
        raise ValueError("Only NYK season caching is supported for the public demo")

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
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Game.id)
                .where(Game.season == season)
                .where((Game.home_team_id == team) | (Game.away_team_id == team))
                .order_by(Game.game_date)
            )
        ).all()
        game_ids = [row[0] for row in rows]

    detail_results = []
    for game_id in game_ids:
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

    async with AsyncSessionLocal() as db:
        games = (
            await db.execute(
                select(Game)
                .where(Game.season == season)
                .where((Game.home_team_id == team) | (Game.away_team_id == team))
            )
        ).scalars().all()
        summary = {
            "team": team,
            "season": season,
            "include_playoffs": include_playoffs,
            "games_result": games_result,
            "total_games": len(games),
            "summary_only": sum(1 for g in games if g.data_status == "summary_only"),
            "events_ready": sum(1 for g in games if g.data_status == "events_ready"),
            "analysis_ready": sum(1 for g in games if g.data_status == "analysis_ready"),
            "detail_results": detail_results,
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


def cache_season_main() -> None:
    parser = argparse.ArgumentParser(description="Cache Knicks season data")
    parser.add_argument("--team", default="NYK")
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--include-playoffs", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(_cache_season(args.team, args.season, args.include_playoffs))
    print(json.dumps(result, indent=2, default=str))


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


async def _build_rag_index(season: str, out_dir: str) -> dict:
    async with AsyncSessionLocal() as db:
        return await build_rag_artifacts(
            db,
            season=season,
            out_dir=Path(out_dir),
            summary_model=get_settings().openrouter_summary_model,
        )


def build_rag_index_main() -> None:
    parser = argparse.ArgumentParser(
        description="Build derived RAG artifacts from the current cached DB only"
    )
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--out-dir", default="rag-artifacts")
    args = parser.parse_args()
    result = asyncio.run(_build_rag_index(args.season, args.out_dir))
    print(json.dumps(result, indent=2, default=str))
