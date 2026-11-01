"""Tests for worker CLI argument parsing."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

os.environ["TEST_MODE"] = "true"
os.environ["LOG_JSON"] = "false"

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.core.seed_loader import seed_all, seed_teams  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.game import Game  # noqa: E402
from worker_app import cli  # noqa: E402
from worker_app.cli import _build_rag_index_parser, _cache_season_parser  # noqa: E402


@pytest.fixture(scope="function")
async def worker_db() -> AsyncIterator:
    """Yield a fresh DB with the worker's expected schema."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def test_build_rag_index_parser_accepts_staged_index_flags():
    args = _build_rag_index_parser().parse_args(
        [
            "--season",
            "2025-26",
            "--out-dir",
            "rag-artifacts",
            "--game-limit",
            "10",
            "--game-order",
            "recent",
            "--reset-qdrant",
        ]
    )

    assert args.season == "2025-26"
    assert args.out_dir == "rag-artifacts"
    assert args.game_limit == 10
    assert args.game_order == "recent"
    assert args.reset_qdrant is True


def test_build_rag_index_parser_defaults_keep_full_chronological_index():
    args = _build_rag_index_parser().parse_args([])

    assert args.game_limit is None
    assert args.game_order == "date"
    assert args.reset_qdrant is False


def test_cache_season_parser_accepts_demo_ready_flags():
    args = _cache_season_parser().parse_args(
        [
            "--team",
            "NYK",
            "--season",
            "2025-26",
            "--include-playoffs",
            "--demo-ready",
            "--rag-out-dir",
            "tmp-rag",
            "--reset-qdrant",
        ]
    )

    assert args.team == "NYK"
    assert args.season == "2025-26"
    assert args.include_playoffs is True
    assert args.demo_ready is True
    assert args.rag_out_dir == "tmp-rag"
    assert args.reset_qdrant is True


async def test_demo_ready_cache_marks_all_cached_games_analysis_ready(
    worker_db, monkeypatch, tmp_path
):
    async with AsyncSessionLocal() as db:
        await seed_all(db)

    async def fake_build_rag_artifacts(db, **kwargs):
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.season == kwargs["season"])
                    .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
                )
            )
            .scalars()
            .all()
        )
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        return {
            "selected_game_count": len(games),
            "possession_chunk_count": len(games),
            "table_export": str(out_dir / "games_table.json"),
        }

    monkeypatch.setattr(cli, "build_rag_artifacts", fake_build_rag_artifacts)

    result = await cli._cache_season(
        "NYK",
        "2025-26",
        True,
        demo_ready=True,
        rag_out_dir=str(tmp_path),
    )

    assert result["ready"] is True
    assert result["total_games"] > 0
    assert result["analysis_ready"] == result["total_games"]
    assert result["summary_only"] == 0
    assert result["events_ready"] == 0
    assert result["failed_games"] == []
    assert result["rag_artifacts_built"] is True


async def test_demo_ready_cache_requires_live_source_outside_test_mode(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(test_mode=False, data_source="static"),
    )

    with pytest.raises(ValueError, match="NBA_DATA_SOURCE=nba_api"):
        await cli._cache_season("NYK", "2025-26", True, demo_ready=True)


async def test_demo_ready_cache_fails_gate_when_cached_game_has_no_events(
    worker_db, monkeypatch, tmp_path
):
    from app.models.game import Game

    async with AsyncSessionLocal() as db:
        await seed_teams(db)
        db.add(
            Game(
                nba_game_id="0099900001",
                season="2025-26",
                game_date=date(2026, 1, 1),
                home_team_id="NYK",
                away_team_id="BOS",
                home_score=99,
                away_score=98,
                status="final",
                season_type="regular",
                data_status="summary_only",
            )
        )
        await db.commit()

    async def fake_ingest_games(**kwargs):
        return {
            "inserted_game_ids": [],
            "skipped_nba_game_ids": ["0099900001"],
            "seasons_processed": [kwargs["season"]],
            "include_playoffs": kwargs["include_playoffs"],
        }

    async def fake_ingest_game_detail(**kwargs):
        raise ValueError("No source data for 0099900001")

    async def fake_build_rag_artifacts(db, **kwargs):
        return {"selected_game_count": 1, "possession_chunk_count": 0}

    monkeypatch.setattr(cli, "ingest_games", fake_ingest_games)
    monkeypatch.setattr(cli, "ingest_game_detail", fake_ingest_game_detail)
    monkeypatch.setattr(cli, "build_rag_artifacts", fake_build_rag_artifacts)

    result = await cli._cache_season(
        "NYK",
        "2025-26",
        True,
        demo_ready=True,
        rag_out_dir=str(tmp_path),
    )

    assert result["ready"] is False
    assert result["summary_only"] == 1
    assert result["analysis_ready"] == 0
    assert result["failed_games"]
