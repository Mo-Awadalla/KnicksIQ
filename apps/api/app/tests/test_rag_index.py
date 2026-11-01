"""Tests for staged local RAG indexing."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.core.config import get_settings
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.rag_index import build_rag_artifacts
from sqlalchemy import delete


async def _replace_games(db_session, count: int) -> list[Game]:
    await db_session.execute(delete(GameEvent))
    await db_session.execute(delete(Game))
    games = [
        Game(
            nba_game_id=f"staged-{index}",
            season="2025-26",
            game_date=date(2025, 10, 1) + timedelta(days=index),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=100 + index,
            away_score=90 + index,
            status="final",
            season_type="regular",
            data_status="events_ready",
        )
        for index in range(count)
    ]
    db_session.add_all(games)
    await db_session.commit()
    for game in games:
        await db_session.refresh(game)
    return games


async def test_build_rag_artifacts_limits_to_recent_games_and_reports_manifest(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    games = await _replace_games(db_session, 12)
    settings = get_settings().model_copy(update={"rag_qdrant_enabled": False})
    monkeypatch.setattr("app.services.rag_index.get_settings", lambda: settings)
    await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        game_limit=10,
        game_order="recent",
    )
    exported = json.loads((tmp_path / "games_table.json").read_text())
    assert [row["date"] for row in exported] == [
        (date(2025, 10, 1) + timedelta(days=index)).isoformat() for index in range(11, 1, -1)
    ]
    assert {row["game_id"] for row in exported} == {game.id for game in games[2:]}


async def test_build_rag_artifacts_does_not_reset_qdrant_unless_requested(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    await _replace_games(db_session, 1)
    reset_calls: list[str] = []
    ensure_calls: list[bool] = []

    monkeypatch.setattr(
        "app.services.rag_index.build_possession_chunks",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.rag_index.get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            rag_qdrant_enabled=True,
            rag_qdrant_possessions_collection="knicks_possessions",
        ),
    )
    monkeypatch.setattr(
        "app.services.rag_index.recreate_collection",
        lambda collection: reset_calls.append(collection),
    )
    monkeypatch.setattr(
        "app.services.rag_index.ensure_collections",
        lambda: ensure_calls.append(True),
    )

    manifest = await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        reset_qdrant=False,
    )

    assert manifest["qdrant_reset_requested"] is False
    assert manifest["qdrant_reset"] is False
    assert reset_calls == []
    assert ensure_calls == []
